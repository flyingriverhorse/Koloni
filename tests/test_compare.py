"""Slice 54 beyond its acceptance set: what each side and the later turns are sent, a side's
changes decided only by the choice, a choice that clashes with the project, its cost, what a
side may use, its commands, Stop, the CLIs that cannot be a side, the record, the budget and
the backlog."""

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.api import compares
from app.api.compares import cost_of
from app.config import load_settings
from app.db.models import BacklogTask, Compare, Project
from app.main import create_app
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_compare_scenarios import ORIGIN, compared, ready, two  # noqa: F401  (the fixture)
from tests.test_copy_scenarios import seen
from tests.test_mcp_scenarios import give, server
from tests.test_spawn import call, step


def sent(model) -> str:
    return "\n".join(str(m.get("content")) for call in model.calls for m in call)


def test_the_sides_never_see_each_other_and_later_turns_see_only_the_chosen_one(two, project_dir):  # noqa: F811
    client, providers = two([text("Alpha says one."), text("Later, from Alpha.")],
                            [text("Beta says two.")])
    cid, started = compared(client, project_dir, providers, content="say a number")
    alpha_side, beta_side = ready(client, started["compare_id"])["sides"]
    beta = client.app.state.providers.named["Beta"]
    assert "Alpha says one." not in sent(beta)
    client.post(f"/api/compares/{started['compare_id']}/choose", json={"run_id": beta_side["run_id"]})

    # Next on Alpha, the side that lost.
    client.patch(f"/api/conversations/{cid}", json={"provider_id": providers[0]["id"]})
    client.post(f"/api/conversations/{cid}/messages", json={"content": "and now?"})
    alpha = client.app.state.providers.named["Alpha"]
    for _ in range(250):
        if len(alpha.calls) == 2:
            break
        time.sleep(0.02)
    later = "\n".join(str(m.get("content")) for m in alpha.calls[-1])
    assert "Beta says two." in later and "Alpha says one." not in later
    assert later.count("say a number") == 1  # the chosen side's message, once


def test_a_sides_changes_wait_for_the_choice_and_a_clash_is_left_to_the_user(two, project_dir):  # noqa: F811
    client, providers = two([write("hello.py", "print('alpha')\n"), text("a")],
                            [write("hello.py", "print('beta')\n"), text("b")])
    cid, started = compared(client, project_dir, providers)
    alpha, beta = ready(client, started["compare_id"])["sides"]
    kept = {m["run_id"]: m for m in client.get(f"/api/conversations/{cid}").json()["merges"]}
    # Not through its card while the comparison waits: only by choosing.
    refused = client.post(f"/api/merges/{kept[alpha['run_id']]['id']}/approve", json={"choices": {}})
    assert refused.status_code == 409
    assert client.post(f"/api/runs/{alpha['run_id']}/undo").status_code == 409  # nor undone
    assert (project_dir / "hello.py").read_text() == "print('hi')\n"

    (project_dir / "hello.py").write_text("print('mine')\n")  # the user's own, meanwhile
    chosen = client.post(f"/api/compares/{started['compare_id']}/choose", json={"run_id": alpha["run_id"]})
    assert chosen.status_code == 200 and chosen.json()["status"] == "chosen"
    assert (project_dir / "hello.py").read_text() == "print('mine')\n"  # nothing chosen for the user
    after = {m["run_id"]: m for m in client.get(f"/api/conversations/{cid}").json()["merges"]}
    assert after[beta["run_id"]]["status"] == "rejected"
    left = after[alpha["run_id"]]
    assert left["status"] == "kept" and left["files"][0]["state"] == "conflict"
    # ...decided on its card, as any kept copy's.
    taken = client.post(f"/api/merges/{left['id']}/approve", json={"choices": {"hello.py": "agent"}, "shown": seen(left)})
    assert taken.status_code == 200, taken.text
    assert (project_dir / "hello.py").read_text() == "print('alpha')\n"


def test_a_refused_model_or_an_unknown_provider_starts_nothing(two, project_dir):  # noqa: F811
    client, providers = two([], [])
    client.patch(f"/api/providers/{providers[1]['id']}",
                 json={"models": [{"name": "beta-1"}], "only_listed": True})
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    url = f"/api/conversations/{cid}/compare"
    refused = client.post(url, json={"content": "x", "sides": [
        {"provider_id": providers[0]["id"]}, {"provider_id": providers[1]["id"], "model_id": "beta-2"}]})
    assert refused.status_code == 422 and "beta-2 is not one of them" in refused.json()["detail"]
    assert client.get(f"/api/conversations/{cid}").json()["runs"] == []


def test_a_sides_cost_adds_up_the_priced_models_as_the_turns_summary_does():
    one = {"amount": 0.5, "currency": "USD"}
    assert cost_of([{"cost": one}, {"cost": {"amount": 0.25, "currency": "USD"}}]) == [{
        "amount": 0.75, "currency": "USD"}]
    # a model of it with no price, or a part not known: at least that much
    assert cost_of([{"cost": one}, {"cost": None}]) == [{"amount": 0.5, "currency": "USD", "at_least": True}]
    assert cost_of([{"cost": {**one, "cache_unpriced": True}}])[0]["at_least"] is True
    # two currencies: a sum of each, never one added to the other (B-09)
    assert cost_of([{"cost": one}, {"cost": {"amount": 1, "currency": "EUR"}},
                    {"cost": {"amount": 0.25, "currency": "USD", "at_least": True}}]) == [
        {"amount": 0.75, "currency": "USD", "at_least": True}, {"amount": 1, "currency": "EUR"}]
    assert cost_of([{"cost": None}]) is None and cost_of([]) is None


def test_a_side_has_no_servers_tool_nor_one_that_outlives_the_choice_or_opens_another_model(
    two, project_dir, tmp_path  # noqa: F811
):
    client, providers = two([text("a")], [text("b")])
    server(client, tmp_path)
    give(client, "Lead", "fake")
    runner = client.app.state.runner
    runner._note_what_it_found = AsyncMock()
    cid, started = compared(client, project_dir, providers)
    ready(client, started["compare_id"])
    alpha = client.app.state.providers.named["Alpha"]
    offered = {schema["function"]["name"] for schema in alpha.tool_args[0]}
    assert "write_file" in offered and "run_command" in offered  # it works itself (slice 48 or not)
    assert not offered & {"spawn_agent", "message_agent", "discuss", "open_room", "remember",
                          "create_role", "add_skill", "ask_folder", "add_task", "change_task",
                          "assess_task"}
    assert "read_backlog" in offered  # reading changes nothing
    assert not any("__" in name for name in offered)  # no MCP server's tool
    leads = [a for a in client.get(f"/api/conversations/{cid}").json()["agents"] if a["depth"] == 0]
    assert [lead["mcp"] for lead in leads] == [[], []]
    runner._note_what_it_found.assert_not_awaited()  # nothing of a side goes into the journal


def test_a_sides_command_runs_in_its_copy(two, project_dir):  # noqa: F811
    made = call("run_command", {"command": "python -c \"open('made.txt','w').write('x')\""})
    client, providers = two([step(made), text("ran it")], [text("b")])
    _cid, started = compared(client, project_dir, providers)
    alpha, _beta = ready(client, started["compare_id"])["sides"]
    assert not (project_dir / "made.txt").exists()
    assert alpha["changed_files"] == ["made.txt"]


def test_the_chosen_sides_findings_are_noted_at_the_choice(two, project_dir):  # noqa: F811
    note = '[{"text": "The greeting is spelled merhaba.", "about": "greeting"}]'
    client, providers = two([text("Alpha: hallo.")],
                            [write("greeting.txt", "merhaba\n"), text("Beta: merhaba."), text(note)])
    # Beta's model is the team's fast one too: it is the one asked for notes.
    assert client.patch(f"/api/providers/{providers[1]['id']}", json={
        "for_agents": True, "models": [{"name": "beta-1", "tier": "fast"}]}).status_code == 200
    cid, started = compared(client, project_dir, providers)
    _alpha, beta = ready(client, started["compare_id"])["sides"]
    pid = client.get("/api/projects").json()[0]["id"]
    assert client.patch(f"/api/projects/{pid}", json={"auto_notes": True}).status_code == 200
    assert client.get(f"/api/projects/{pid}/memory").json()["journal"] == []
    client.post(f"/api/compares/{started['compare_id']}/choose", json={"run_id": beta["run_id"]})
    for _ in range(250):
        if journal := client.get(f"/api/projects/{pid}/memory").json()["journal"]:
            break
        time.sleep(0.02)
    assert [n["text"] for n in journal] == ["The greeting is spelled merhaba."]
    asked = "\n".join(str(m.get("content")) for m in client.app.state.providers.named["Beta"].calls[-1])
    assert "Beta: merhaba." in asked and "Alpha: hallo." not in asked
    assert 'Files changed in the turn: "greeting.txt"' in asked  # taken in before it is asked


def test_a_sides_install_into_the_shared_node_modules_is_asked_in_full_auto_too(two, project_dir):  # noqa: F811
    (project_dir / "node_modules").mkdir()  # linked into the copy: the project's own
    install = call("run_command", {"command": "npm install left-pad"})
    client, providers = two([step(install), text("a")], [text("b")])
    cid, _started = compared(client, project_dir, providers)
    for _ in range(250):
        if commands := client.get(f"/api/conversations/{cid}").json()["commands"]:
            break
        time.sleep(0.02)
    assert [c["status"] for c in commands] == ["proposed"]  # (unasked without the K-54 rule)


def test_a_side_stopped_keeps_nothing_and_the_other_goes_on(two, project_dir):  # noqa: F811
    async def held(_on_delta):
        await asyncio.Event().wait()

    client, providers = two([write("a.txt", "a\n"), held], [text("b")])
    cid, started = compared(client, project_dir, providers)
    for _ in range(250):
        if client.get(f"/api/compares/{started['compare_id']}").json()["sides"][0]["changed_files"]:
            break
        time.sleep(0.02)
    assert client.post(f"/api/runs/{started['run_ids'][0]}/cancel").status_code == 202
    alpha, beta = ready(client, started["compare_id"])["sides"]
    assert (alpha["status"], alpha["changed_files"], beta["answer"]) == ("cancelled", [], "b")
    assert not (project_dir / "a.txt").exists()
    assert client.get(f"/api/conversations/{cid}").json()["merges"] == []


def test_a_cli_that_could_write_outside_its_copy_or_needs_full_auto_is_no_side(settings_env, project_dir):
    clients = {
        "Alpha": ScriptedModel([]),
        "Native": SimpleNamespace(native=True, own_copy=True),  # as Codex: needs Full auto
        "Agy": SimpleNamespace(native=True, own_copy=True, sandboxed=False),
    }
    app = create_app(load_settings(settings_env), model=ScriptedModel([]), clients=clients)
    with TestClient(app, base_url="http://127.0.0.1:8790", headers=ORIGIN) as client:
        ids = {name: client.post("/api/providers", json={
            "name": name, "kind": "openai_compat", "base_url": "http://127.0.0.1:9/v1"}).json()["id"]
            for name in clients}
        pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
        cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]

        def start(name):
            sides = [{"provider_id": ids["Alpha"]}, {"provider_id": ids[name]}]
            return client.post(f"/api/conversations/{cid}/compare", json={"content": "x", "sides": sides})

        asked = start("Native")
        assert asked.status_code == 422 and "Set the permission level to Full auto" in asked.json()["detail"]
        agy = start("Agy")
        assert agy.status_code == 422 and "cannot work in a side of a comparison" in agy.json()["detail"]
        assert client.get(f"/api/conversations/{cid}").json()["runs"] == []


def test_the_loser_is_only_thrown_away_where_the_choice_broke_off(two, project_dir):  # noqa: F811
    client, providers = two([write("a.txt", "a\n"), text("a")], [write("b.txt", "b\n"), text("b")])
    cid, started = compared(client, project_dir, providers)
    alpha, beta = ready(client, started["compare_id"])["sides"]
    runner = client.app.state.runner
    decide = runner.decide_kept

    async def broke_off(merge_id, decision, choices=None):  # the loser's throwing away never ran
        return decision == "approve" and await decide(merge_id, decision, choices)

    runner.decide_kept = broke_off
    chose = client.post(f"/api/compares/{started['compare_id']}/choose", json={"run_id": alpha["run_id"]})
    runner.decide_kept = decide
    assert chose.status_code == 200
    assert (project_dir / "a.txt").exists() and not (project_dir / "b.txt").exists()
    merges = client.get(f"/api/conversations/{cid}").json()["merges"]
    loser = next(m for m in merges if m["run_id"] == beta["run_id"])
    assert loser["status"] == "kept"
    assert client.post(f"/api/merges/{loser['id']}/approve", json={"choices": {}}).status_code == 409
    assert client.post(f"/api/merges/{loser['id']}/reject").status_code == 200
    assert not (project_dir / "b.txt").exists()


def test_the_record_says_how_often_a_models_work_was_chosen(two, project_dir):  # noqa: F811
    client, providers = two([text("a")], [text("b")])
    _cid, started = compared(client, project_dir, providers)
    _alpha, beta = ready(client, started["compare_id"])["sides"]
    client.post(f"/api/compares/{started['compare_id']}/choose", json={"run_id": beta["run_id"]})
    rows = {row["model_id"]: row for row in client.get("/api/record").json()["rows"]}
    assert rows["alpha-1"]["compared"] == {"chosen": 0, "not_chosen": 1}
    assert rows["beta-1"]["compared"] == {"chosen": 1, "not_chosen": 0}


def started_in(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto"})
    return pid, cid


def test_over_the_budget_a_comparison_waits_for_the_users_word_as_a_message_does(
    two, project_dir, monkeypatch  # noqa: F811
):
    client, providers = two([text("a")], [text("b")])
    monkeypatch.setattr(compares, "over_budget", lambda session, project, **_: "over this month's budget")
    _pid, cid = started_in(client, project_dir)
    body = {"content": "x", "sides": [{"provider_id": p["id"]} for p in providers]}
    refused = client.post(f"/api/conversations/{cid}/compare", json=body)
    assert refused.status_code == 409 and "budget" in refused.json()["detail"]
    assert client.get(f"/api/conversations/{cid}").json()["runs"] == []
    going = client.post(f"/api/conversations/{cid}/compare", json={**body, "over_budget": True})
    assert going.status_code == 201, going.text
    ready(client, going.json()["compare_id"])


def test_a_comparison_in_a_tasks_conversation_leaves_the_backlog_as_it_was(two, project_dir):  # noqa: F811
    client, providers = two([text("a")], [text("b")])
    runner = client.app.state.runner
    runner._assess = AsyncMock()
    pid, cid = started_in(client, project_dir)
    doing, todo = (client.post(f"/api/projects/{pid}/backlog", json={"title": t}).json()["id"]
                   for t in ("doing", "todo"))
    with client.app.state.session_factory() as session:
        task = session.get_one(BacklogTask, doing)
        task.status, task.conversation_id = "doing", cid
        session.get_one(Project, pid).backlog_auto = True
        session.commit()
    body = {"content": "x", "sides": [{"provider_id": p["id"]} for p in providers]}
    started = client.post(f"/api/conversations/{cid}/compare", json=body)
    assert started.status_code == 201, started.text
    ready(client, started.json()["compare_id"])
    tasks = {t["id"]: t for t in client.get(f"/api/projects/{pid}/backlog").json()}
    assert (tasks[doing]["status"], tasks[doing]["conversation_id"]) == ("doing", cid)
    assert (tasks[todo]["status"], tasks[todo]["conversation_id"]) == ("todo", None)  # no chain
    assert client.get(f"/api/projects/{pid}/backlog/auto").json().items() >= {"on": True, "halt": None}.items()
    runner._assess.assert_not_awaited()


def test_a_comparison_goes_on_with_the_topic_the_box_names(two, project_dir):  # noqa: F811
    client, providers = two([text("a"), text("a2"), text("a3")], [text("b"), text("b2"), text("b3")])
    cid, started = compared(client, project_dir, providers, content="first piece")
    seen = ready(client, started["compare_id"])
    client.post(f"/api/compares/{started['compare_id']}/choose", json={"run_id": seen["sides"][0]["run_id"]})
    first = client.get(f"/api/conversations/{cid}").json()["runs"][0]["topic_id"]
    sides = [{"provider_id": p["id"]} for p in providers]

    def topic_of(**where):
        going = client.post(f"/api/conversations/{cid}/compare", json={"content": "more", "sides": sides, **where})
        assert going.status_code == 201, going.text
        done = ready(client, going.json()["compare_id"])
        client.post(f"/api/compares/{done['id']}/discard")
        runs = {r["id"]: r for r in client.get(f"/api/conversations/{cid}").json()["runs"]}
        return {runs[run_id]["topic_id"] for run_id in going.json()["run_ids"]}

    fresh = topic_of(new_topic=True)
    assert len(fresh) == 1 and first not in fresh  # both sides in one new topic
    # named: the first one, not the topic the user was last in (the new one)
    assert topic_of(topic_id=first) == {first}


def test_discard_both_while_they_work_stops_them_and_keeps_nothing(two, project_dir):  # noqa: F811
    async def held(_on_delta):
        await asyncio.Event().wait()

    client, providers = two([write("a.txt", "a\n"), held], [write("b.txt", "b\n"), text("b")])
    cid, started = compared(client, project_dir, providers)
    for _ in range(250):
        if client.get(f"/api/compares/{started['compare_id']}").json()["sides"][0]["changed_files"]:
            break
        time.sleep(0.02)
    thrown = client.post(f"/api/compares/{started['compare_id']}/discard")
    assert thrown.status_code == 200, thrown.text
    alpha, beta = ready(client, started["compare_id"])["sides"]
    deadline = time.monotonic() + 10
    while alpha["status"] not in ("cancelled", "interrupted"):
        assert time.monotonic() < deadline, alpha
        time.sleep(0.05)
        alpha, beta = client.get(f"/api/compares/{started['compare_id']}").json()["sides"]
    assert beta["status"] == "cancelled" and not beta["answer"]  # the queued side never started
    assert client.get(f"/api/compares/{started['compare_id']}").json()["status"] == "discarded"
    assert not (project_dir / "a.txt").exists() and not (project_dir / "b.txt").exists()
    assert client.get(f"/api/conversations/{cid}").json()["merges"] == []


def test_the_chosen_sides_changes_can_be_undone(two, project_dir):  # noqa: F811
    client, providers = two([write("hello.py", "print('alpha')\n"), text("a")], [text("b")])
    _cid, started = compared(client, project_dir, providers)
    alpha, _beta = ready(client, started["compare_id"])["sides"]
    client.post(f"/api/compares/{started['compare_id']}/choose", json={"run_id": alpha["run_id"]})
    assert (project_dir / "hello.py").read_text() == "print('alpha')\n"
    undone = client.post(f"/api/runs/{alpha['run_id']}/undo")
    assert undone.status_code == 200 and undone.json()["revert"] == ["hello.py"], undone.text
    assert (project_dir / "hello.py").read_text() == "print('hi')\n"


def test_a_side_that_ends_after_both_were_thrown_away_keeps_nothing(two, project_dir):  # noqa: F811
    go_on = threading.Event()

    async def late(_on_delta):  # it ends only once the comparison is discarded
        await asyncio.to_thread(go_on.wait, 10)
        return text("a")

    client, providers = two([write("a.txt", "a\n"), late], [text("b")])
    cid, started = compared(client, project_dir, providers)
    for _ in range(250):
        if client.get(f"/api/compares/{started['compare_id']}").json()["sides"][0]["changed_files"]:
            break
        time.sleep(0.02)
    with client.app.state.session_factory() as session:  # as the discard's record, before its Stop lands
        session.get_one(Compare, started["compare_id"]).status = "discarded"
        session.commit()
    go_on.set()
    for _ in range(250):
        if client.get(f"/api/compares/{started['compare_id']}").json()["sides"][0]["status"] == "completed":
            break
        time.sleep(0.02)
    assert client.get(f"/api/conversations/{cid}").json()["merges"] == []
    assert not (project_dir / "a.txt").exists()
