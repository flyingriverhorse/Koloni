"""B-301's acceptance set: a role that may not both write and run works on every CLI, recipes too.

The user (R94): "bunun düzeltilmesi lazım … her model yapabilmeli bunu". A role short of the write
and command tools (Product owner, Spec writer, Reviewer; and, on Codex, a Tester) is started
read-only on the CLI's own side: Codex in its read-only sandbox, Copilot with its view tool only,
agy reading. Its own writes are refused; it writes only with KOLONİ's write_file over the bridge,
which lands where KOLONİ decides - a recipe's copy, taken in by the user. A role that runs commands
is refused where it was (Copilot and agy at a recipe's step). The ladder: a provider the role
cannot run on as a step is passed over for the next.
"""

import json
import sys
from itertools import pairwise
from pathlib import Path

import pytest

from app.config import load_settings
from app.main import create_app
from app.team import ONLY_IN_THE_PROJECT
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, teams_of
from tests.test_copilot_agent import HEADLESS, SERVER
from tests.test_parallel import until
from tests.test_recipe_run_scenarios import READY, answer, asked, by_call, made, manual
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import begin, role_id, spawn

HERE = Path(__file__).parent
CODEX = [sys.executable, str(HERE / "fake_codex_app_server.py")]
AGY = [sys.executable, str(HERE / "fake_agy_cli.py")]
SPEC = "# Spec\n\n- It greets.\n"
# Each CLI tries its own write first, then KOLONİ's read_file and write_file over the bridge.
# (Codex has no shell here: a command of its own would end the turn - its own test below.)
OWN_THEN_KOLONI = {
    "Codex": [{"write": "docs/own.md", "content": "mine\n"},
              {"koloni": "read_file", "args": {"path": "hello.py"}},
              {"koloni": "write_file", "args": {"path": "docs/spec.md", "content": SPEC}},
              {"say": "Wrote docs/spec.md."}],
    "Copilot": [{"write": "docs/own.md", "content": "mine\n"},
                {"koloni": "write_file", "args": {"path": "docs/spec.md", "content": SPEC}},
                {"say": "Wrote docs/spec.md."}],
}


@pytest.fixture
def clis(settings_env, tmp_path):
    """An app whose Lead is scripted and that has the stand-in Codex, Copilot and agy (reading),
    each with a plan of its own; `make.record(name)` reads what that CLI wrote down."""
    from app.model_agy import AgyClient
    from app.model_native import CodexNativeClient, CopilotNativeClient

    opened, plans = [], {}

    def plan(name, script, **more):
        record, told = tmp_path / f"{name}-record.json", tmp_path / f"{name}-plan.json"
        told.write_text(json.dumps({"record": str(record), "script": script, **more}),
                        encoding="utf-8")
        plans[name] = record
        return str(told)

    def make(lead, codex=(), copilot=(), agy=(), fast=()):
        clients = {
            "Codex": CodexNativeClient(launcher=CODEX, timeout=30,
                                       env={"FAKE_CLI_PLAN": plan("Codex", list(codex))}),
            "Copilot": CopilotNativeClient(
                None, "qwen-local", timeout=30, launcher=HEADLESS,
                env={"FAKE_CLI_PLAN": plan("Copilot", list(copilot))},
                base_url=SERVER["base_url"], api_key=SERVER["api_key"], options=SERVER["options"]),
            "agy": AgyClient(None, "gemini-asked", timeout=30, launcher=AGY,
                             env={"FAKE_AGY_PLAN": plan("agy", list(agy))}),
            "Fast": ScriptedModel(list(fast), model_id="quick"),
        }
        app = create_app(load_settings(settings_env), model=ScriptedModel(lead, model_id="big"),
                         clients=clients)
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        client.headers["Origin"] = OWN["Origin"]  # (Copilot's model server is the page's)
        made_ = {}
        for body in (
            {"name": "Codex", "kind": "codex_cli", "mode": "native"},
            {"name": "Copilot", "kind": "copilot_cli", "mode": "native", **SERVER},
            {"name": "agy", "kind": "agy_cli", "mode": "reads", "default_model": "gemini-asked"},
            {"name": "Fast", "kind": "openai_compat", "base_url": "http://127.0.0.1:9/v1",
             "default_model": "quick"},
        ):
            answer_ = client.post("/api/providers", json=body)
            assert answer_.status_code == 201, answer_.text
            made_[body["name"]] = answer_.json()
        return client, made_

    make.record = lambda name: json.loads(plans[name].read_text(encoding="utf-8"))
    make.plan = plan  # (a CLI's plan again, before its run)
    yield make
    for client in opened:
        client.__exit__(None, None, None)


def on(client, providers, provider, *roles):
    for role in roles:
        assert client.patch(f"/api/roles/{role_id(client, role)}", json={
            "provider_id": providers[provider]["id"]}).status_code == 200


REPORT = ({"id": "end", "then": "report"},)


def product_recipe(client, ends=None):
    return made(client, "Plan then spec", graph(
        [part("po", "Plan the tasks", {"role": "Product owner"}),
         part("spec", "Write the spec", {"role": "Spec writer"})],
        [("start", "po"), ("po", "spec"), ("spec", "end")], **({"ends": ends} if ends else {})))


LEAD = [spawn("Product owner", "plan the greeting work", "p0"),
        spawn("Spec writer", "write docs/spec.md", "s0"), text("done")]


def taken_in(client, project_dir, wait_run):
    """The Product team's recipe run to Ready for you, its spec still only in the recipe's copy;
    then taken in. The spawn results."""
    cid, run_id = manual(client, project_dir, (teams_of(client)["Product"], product_recipe(client)))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=60)
    assert not (project_dir / "docs").exists()  # KOLONİ's write_file wrote in the recipe's copy
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id, timeout=60)
    assert (project_dir / "docs" / "spec.md").read_bytes() == SPEC.encode()
    assert not (project_dir / "docs" / "own.md").exists()  # its own write never happened
    return by_call(snap), snap


# --- only Codex ------------------------------------------------------------------------------


def test_only_codex_runs_the_product_recipe_read_only_writing_through_koloni(
        clis, wait_run, project_dir):
    client, providers = clis(LEAD, codex=OWN_THEN_KOLONI["Codex"])
    on(client, providers, "Codex", "Product owner", "Spec writer")
    calls, snap = taken_in(client, project_dir, wait_run)
    assert [status for status, _said in calls] == ["succeeded", "succeeded"], calls
    seen = clis.record("Codex")  # (the Spec writer's, the last run)
    assert seen["thread"]["sandbox"] == "read-only" and "sandboxPolicy" not in seen["turn"]
    assert set(pairwise(seen["argv"])) >= NO_SHELL  # no shell of its own at all
    # its own patch declined; KOLONİ's read and write tools over the bridge instead
    assert [(a["method"], a["answer"]) for a in seen["answers"]][:1] == [
        ("item/fileChange/requestApproval", {"decision": "decline"})]
    assert {"read_file", "list_dir", "search", "write_file"} <= set(seen["tools"])
    assert "print('hi')" in json.dumps(seen["results"][0])  # its read_file, through KOLONİ
    # told before it starts, after the rules that speak of its own tools: read with KOLONİ's
    told = seen["stdin"][:seen["stdin"].index("\n\n{")]
    assert "started you read-only" in told and "list_dir and search" in told
    assert snap["file_changes"] and all(c["origin"] != "cli" for c in snap["file_changes"])


NO_SHELL = {("-c", "features.shell_tool=false"), ("-c", "features.unified_exec=false")}


def test_a_codex_reviewers_own_command_ends_its_turn_even_one_it_runs_unasked(
        clis, wait_run, project_dir):
    # A known-safe command runs unasked at "untrusted", and the read-only sandbox keeps writes,
    # not reads: with no shell that cannot come; if it comes all the same, the run stops.
    client, providers = clis([spawn("Reviewer", "review it", "r0"), text("done")],
                             codex=[{"run": "type .env", "unasked": True, "output": "TOKEN=x"},
                                    {"say": "read it"}])
    on(client, providers, "Codex", "Reviewer")
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = by_call(snap)
    assert status == "failed" and "started without its shell" in said
    assert set(pairwise(clis.record("Codex")["argv"])) >= NO_SHELL


def test_a_codex_reviewers_read_of_a_secret_through_koloni_is_a_card(clis, wait_run, project_dir):
    from app.workspace import SECRET_CARD
    from tests.test_secret_read import next_pending

    (project_dir / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    client, providers = clis([spawn("Reviewer", "review it", "r0"), text("done")],
                             codex=[{"koloni": "read_file", "args": {"path": ".env"}},
                                    {"say": "read it"}])
    on(client, providers, "Codex", "Reviewer")
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    card = next_pending(client, cid, set())
    assert card["name"] == "read_file" and card["why_asked"] == SECRET_CARD
    assert client.post(f"/api/tool-calls/{card['id']}/reject").status_code == 200
    wait_run(client, cid, run_id)
    assert "TOKEN=x" not in json.dumps(clis.record("Codex")["results"])


def test_a_codex_that_answers_read_only_with_a_writable_sandbox_is_stopped(
        clis, wait_run, project_dir):
    client, providers = clis([spawn("Reviewer", "review it", "r0"), text("done")],
                             codex=[{"say": "never"}])
    on(client, providers, "Codex", "Reviewer")
    clis.plan("Codex", [{"say": "never"}], handshake="writable")
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = by_call(snap)
    assert status == "failed" and '"workspaceWrite", not read-only' in said


def test_a_codex_tester_runs_its_command_in_the_read_only_sandbox_through_kolonis_approval(
        clis, wait_run, project_dir):
    client, providers = clis([spawn("Tester", "run the tests", "t0"), text("done")],
                             codex=[{"run": "pytest -q", "output": "1 passed"}, {"say": "1 passed"}])
    on(client, providers, "Codex", "Tester")
    cid, run_id = begin(client, project_dir, mode="ask", spawn_approval="never")
    snap = until(client, cid, lambda s: any(c["status"] == "proposed" for c in s["commands"]),
                 timeout=30)
    # at Ask its command is a card, as any command of a role that runs them
    (card,) = [c for c in snap["commands"] if c["status"] == "proposed"]
    assert client.post(f"/api/commands/{card['id']}/approve", json={}).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert [status for status, _said in by_call(snap)] == ["succeeded"]
    seen = clis.record("Codex")
    assert seen["thread"]["sandbox"] == "read-only"
    assert not NO_SHELL & set(pairwise(seen["argv"]))  # its shell, read-only
    assert [(a["method"], a["answer"]) for a in seen["answers"]] == [
        ("item/commandExecution/requestApproval", {"decision": "accept"})]


def test_a_codex_coder_still_works_in_its_writable_sandbox(clis, wait_run, project_dir):
    client, providers = clis([spawn("Coder", "fix it", "c0"), text("done")],
                             codex=[{"say": "nothing to fix"}])
    on(client, providers, "Codex", "Coder")
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    wait_run(client, cid, run_id)
    seen = clis.record("Codex")
    assert seen["thread"]["sandbox"] == "workspace-write"
    assert "started you read-only" not in seen["stdin"]


# --- only Copilot ----------------------------------------------------------------------------


def test_only_copilot_runs_the_product_recipe_with_its_view_tool_only(clis, wait_run, project_dir):
    client, providers = clis(LEAD, copilot=OWN_THEN_KOLONI["Copilot"])
    on(client, providers, "Copilot", "Product owner", "Spec writer")
    calls, _snap = taken_in(client, project_dir, wait_run)
    assert [status for status, _said in calls] == ["succeeded", "succeeded"], calls
    seen = clis.record("Copilot")
    given = seen["create"]["availableTools"]
    assert "view" in given and not {"powershell", "create", "edit"} & set(given)
    assert "koloni-write_file" in given and "koloni-read_file" in given
    # its own write, asked all the same, is refused (KOLONİ's answer)
    assert [(a["kind"], a["result"]["kind"]) for a in seen["answers"]][0] == ("write", "reject")


def test_a_copilot_tester_is_still_no_recipes_step(clis, wait_run, project_dir):
    # The boundary is where it was: its commands could write in the project itself.
    client, providers = clis([spawn("Tester", "test it", "t0"), text("done")])
    on(client, providers, "Copilot", "Tester")
    tested = made(client, "Test it", graph([part("t", "Test", {"role": "Tester"})],
                                           [("start", "t"), ("t", "end")]))
    cid, run_id = manual(client, project_dir, (teams_of(client)["Quality"], tested))
    snap = wait_run(client, cid, run_id, timeout=30)
    ((status, said),) = by_call(snap)
    assert status == "failed" and ONLY_IN_THE_PROJECT.format(provider="Copilot") in said


# --- only agy ----------------------------------------------------------------------------------


def test_agy_reading_runs_the_product_recipe_writing_its_spec_through_koloni(
        clis, wait_run, project_dir):
    # B-310: KOLONİ's bridge in agy's home, so a Spec writer reading only writes its document
    # with KOLONİ's write_file - in the recipe's copy, taken in by the user.
    client, providers = clis(LEAD, agy=[
        {"tool": "run_command", "asks": True, "parameters": {"CommandLine": "echo x > a.txt"},
         "touches": {"a.txt": "x"}},
        {"tool": "write_to_file", "asks": True,
         "parameters": {"TargetFile": "docs/own.md", "CodeContent": "mine\n"},
         "touches": {"docs/own.md": "mine\n"}},
        {"koloni": "write_file", "args": {"path": "docs/spec.md", "content": SPEC}},
        {"say": "Wrote docs/spec.md."}])
    on(client, providers, "agy", "Product owner", "Spec writer")
    calls, snap = taken_in(client, project_dir, wait_run)
    assert [status for status, _said in calls] == ["succeeded", "succeeded"], calls
    seen = clis.record("agy")  # (the Spec writer's, the last run)
    # started reading - without leave to write or run - its own command and write refused by
    # agy itself; KOLONİ's write_file allowed by name, and told to write with it
    assert "--dangerously-skip-permissions" not in seen["argv"]
    assert "write_file" in seen["tools"] and "mcp(koloni/write_file)" in seen["allowed"]
    assert "started you read-only" in json.loads(seen["stdin"])["message"]["content"]
    assert not (project_dir / "a.txt").exists()
    refused = [t for t in snap["tool_calls"] if t["name"].endswith("run_command")]
    assert refused and all(t["status"] in ("denied", "failed") for t in refused), refused
    assert snap["file_changes"] and all(c["origin"] != "cli" for c in snap["file_changes"])


PO_TOOLS = {"read_file", "list_dir", "search", "ask_user", "message_agent", "read_backlog",
            "add_task", "change_task", "assess_task", "post_note", "read_notes", "remember",
            "recall"}


def test_a_product_owner_on_agy_reads_the_backlog_through_kolonis_bridge(
        clis, wait_run, project_dir):
    # B-315 (R106): without it, it searched the files for the To-do list for 17 minutes.
    client, providers = clis([spawn("Product owner", "plan the work", "p0"), text("done")],
                             agy=[{"koloni": "read_backlog", "args": {}},
                                  {"say": "The list is empty."}])
    on(client, providers, "agy", "Product owner")
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = by_call(snap)
    assert status == "succeeded", said
    seen = clis.record("agy")
    # every tool of its role, through the bridge, each allowed by its own rule
    assert set(seen["tools"]) >= PO_TOOLS, set(seen["tools"])
    assert seen["allowed"] == sorted(f"mcp(koloni/{tool})" for tool in seen["tools"])
    assert not seen["results"][0]["isError"], seen["results"]
    assert ("read_backlog", "succeeded") in [(t["name"], t["status"]) for t in snap["tool_calls"]]


def test_a_product_owner_on_an_agy_whose_bridge_never_comes_is_not_left_to_wander(
        clis, wait_run, project_dir, monkeypatch):
    import app.model_agy

    monkeypatch.setattr(app.model_agy, "BRIDGE_SECONDS", 0.5)
    client, providers = clis([spawn("Product owner", "plan the work", "p0"), text("done")],
                             agy=[{"say": "never told its task"}])
    clis.plan("agy", [{"say": "never told its task"}], no_bridge=True)
    on(client, providers, "agy", "Product owner")
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    ((status, said),) = by_call(snap)
    assert status == "failed" and "needs KOLONİ's own tools (add_task, assess_task" in said, said
    assert "agy did not start KOLONİ's bridge" in said
    assert clis.record("agy")["stdin"] in (None, "")  # never given its task


# --- the ladder ---------------------------------------------------------------------------------


def balanced(client, providers, *names):
    for name in names:
        assert client.patch(f"/api/providers/{providers[name]['id']}", json={
            "for_agents": True, "models": [{"name": providers[name]["default_model"],
                                            "tier": "balanced"}]}).status_code == 200


def coder_step(client, project_dir):
    built = made(client, "Build it", graph([part("b", "Build", {"role": "Coder"})],
                                           [("start", "b"), ("b", "end")], ends=REPORT))
    return manual(client, project_dir, (teams_of(client)["Web app"], built))


def test_a_tier_passes_over_a_provider_a_step_cannot_run_on_for_the_next(clis, wait_run, project_dir):
    client, providers = clis([spawn("Coder", "fix it", "c0"), text("done")], fast=[text("fixed")])
    balanced(client, providers, "Copilot", "Fast")  # Copilot first in the tier's order
    cid, run_id = coder_step(client, project_dir)
    snap = wait_run(client, cid, run_id, timeout=30)
    coder = next(a for a in snap["agents"] if a["role_name"] == "Coder")
    assert coder["provider_name"] == "Fast" and by_call(snap)[0][0] == "succeeded"
    assert coder["model_id"] == "quick" and coder["chosen_why"].startswith(
        "Copilot works with tools of its own in the project itself")


def test_the_conversations_provider_a_step_cannot_run_on_gives_way_to_the_next(
        clis, wait_run, project_dir):
    client, providers = clis({"Lead": [spawn("Coder", "fix it", "c0"), text("done")],
                              "Coder": [text("fixed")]})
    assert client.patch(f"/api/providers/{providers['Copilot']['id']}",
                        json={"for_agents": True}).status_code == 200
    # the Lead on a model of its own; the chat (so its sub-agents) on Copilot
    local = next(p for p in client.get("/api/providers").json() if p["name"] not in providers)
    assert client.patch(f"/api/roles/{role_id(client, 'Lead')}",
                        json={"provider_id": local["id"]}).status_code == 200
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never",
                        teams_mode="manual", provider_id=providers["Copilot"]["id"], teams=[{
                            "team_id": teams_of(client)["Web app"]["id"],
                            "recipe_id": made(client, "Build it", graph(
                                [part("b", "Build", {"role": "Coder"})],
                                [("start", "b"), ("b", "end")], ends=REPORT))["id"]}])
    snap = wait_run(client, cid, run_id, timeout=30)
    coder = next(a for a in snap["agents"] if a["role_name"] == "Coder")
    # the first provider for agents in the user's order that it can run on: the default one -
    # its model and why on the agent's card, not a silent move
    assert coder["provider_name"] == local["name"] and by_call(snap)[0][0] == "succeeded"
    assert coder["model_id"] == "big" and not coder["chosen"]  # (what Local ran it on)
    assert coder["chosen_why"] == (
        "Copilot works with tools of its own in the project itself: the next provider")
    # the Agents page says so for a step, with where it goes, and the row itself is unmoved
    row = next(r for r in client.get(f"/api/roles/models?conversation_id={cid}").json()
               if r["role"] == "Coder")
    assert row["provider_name"] == "Copilot" and row["source"] == "conversation"
    assert row["cannot_step"].startswith(ONLY_IN_THE_PROJECT.format(provider="Copilot"))
    assert f"As a step it runs on {local['name']}" in row["cannot_step"]


# --- B-314: where a read-only role runs when sub-agents may use only Copilot ------------------


def only_copilot(client, providers, used):
    """Copilot the one provider for agents: its strong model balanced, its quick one fast, a step
    down from 80% of its plan, and its plan last read `used`% as `of_copilot` names it."""
    from datetime import UTC, datetime

    from app.db.models import LimitReading, Provider
    from app.limits import account

    copilot = providers["Copilot"]["id"]
    assert client.patch(f"/api/providers/{copilot}", json={
        "for_agents": True, "step_down_at": 80, "models": [
            {"name": "qwen-big", "tier": "balanced"}, {"name": "qwen-local", "tier": "fast"}],
    }).status_code == 200
    with client.app.state.session_factory() as session:
        session.merge(LimitReading(
            account=json.dumps(account(session.get_one(Provider, copilot))),
            read_at=datetime.now(UTC), reading={"source": None, "plan": None, "credits": None,
                                                "windows": [{"name": "premium requests",
                                                             "minutes": None, "used_percent": used,
                                                             "resets_at": None, "stale": False}]}))
        session.commit()


def test_a_read_only_role_on_a_copilot_past_its_share_says_its_model_and_why(
        clis, wait_run, project_dir):
    client, providers = clis([spawn("Reviewer", "review hello.py", "r0"), text("done")],
                             copilot=[{"say": "Looks fine."}])
    only_copilot(client, providers, 92)
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id, timeout=60)
    reviewer = next(a for a in snap["agents"] if a["role_name"] == "Reviewer")
    # (its model as the stand-in Copilot names it; the tier is the one it was picked at)
    assert (reviewer["provider_name"], reviewer["tier"]) == ("Copilot", "fast")
    assert reviewer["chosen_why"] == "Copilot's plan 92% used: fast instead of balanced"
    # started read-only (B-301): of its own tools only its view tool, the rest KOLONİ's bridge
    given = clis.record("Copilot")["create"]["availableTools"]
    assert [tool for tool in given if not tool.startswith("koloni-")] == ["view"]
    row = next(r for r in client.get(f"/api/roles/models?conversation_id={cid}").json()
               if r["role"] == "Reviewer")
    assert (row["provider_name"], row["model_id"], row["source"]) == ("Copilot", "qwen-local", "tier")
    assert row["moved"] == "Copilot's plan 92% used: fast instead of balanced"


def test_a_role_no_copilot_may_run_says_why_it_runs_on_the_conversations_model(
        clis, wait_run, project_dir):
    # A Tester runs commands, which Copilot has no read-only sandbox for: it is passed over.
    client, providers = clis([spawn("Tester", "test hello.py", "t0"), text("done")])
    only_copilot(client, providers, 10)
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    snap = wait_run(client, cid, run_id, timeout=60)
    tester = next(a for a in snap["agents"] if a["role_name"] == "Tester")
    assert tester["provider_name"] != "Copilot"
    why = ("Copilot cannot be chosen now: it works with its own tools and cannot ask before it "
           "writes or runs something, so it only runs at the Full auto permission level, which "
           "is the user's to set. Choose another model, or leave provider out")
    assert tester["chosen_why"] == f"{why.split(':')[0]}: the default provider"
    row = next(r for r in client.get(f"/api/roles/models?conversation_id={cid}").json()
               if r["role"] == "Tester")
    assert row["source"] == "default" and row["moved"] == tester["chosen_why"]
