"""K-bekleyenler, G5.4: an Ask me card's Go on is bound to its step's files as the card showed
them - the files its agents and the agents they opened changed; changed since, the card is
superseded (no longer answered) and asked again, naming the files."""

import hashlib

from app.agent import CHANGED_SINCE, Ctx
from app.db.models import Agent, Conversation, FileChange, Run
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_questions import answer
from tests.test_recipe_run_scenarios import answer as say
from tests.test_recipe_run_scenarios import asked, made, manual, row
from tests.test_recipes_scenarios import graph
from tests.test_recipes_scenarios import step as part
from tests.test_spawn import spawn, step


def test_a_spec_approval_is_asked_again_when_its_file_changed_since(
    make_client, wait_run, project_dir
):
    client, _ = make_client({
        "Lead": [spawn("Spec writer", "write the spec", "s1"), spawn("Coder", "build it", "c1"),
                 text("done")],
        "Spec writer": [step(write("spec.md", "v1\n")), text("the spec")],
        "Coder": [text("built")],
    })
    # The user's Spec writer writes its spec as a file (the built-in one reports it).
    writer = next(r for r in client.get("/api/roles").json() if r["name"] == "Spec writer")
    client.patch(f"/api/roles/{writer['id']}", json={"tools": [*writer["tools"], "write_file"]})
    recipe = made(client, "Spec first", graph(
        [part("spec", "Write the spec", {"role": "Spec writer"}, ask_me=True),
         part("build", "Build it", {"role": "Coder"})],
        [("start", "spec"), ("spec", "build"), ("build", "end")]))
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], recipe))
    card = asked(until(client, cid, asked))
    assert "Write the spec" in card["question"]
    # The spec changes in the recipe's copy while the card waits.
    runner = client.app.state.runner
    copy = runner._copies[runner._recipe_copy[run_id]]
    (copy.root / "spec.md").write_text("v2\n")
    say(client, card, "Go on")

    again = asked(until(client, cid, lambda s: (a := asked(s)) and a["id"] != card["id"]))
    assert again["question"] == CHANGED_SINCE.format(files="spec.md") + card["question"]
    snap = client.get(f"/api/conversations/{cid}").json()
    assert next(q for q in snap["questions"] if q["id"] == card["id"])["status"] == "superseded"
    assert row(snap)["status"] == "running" and row(snap)["steps"][0]["state"] == "now"
    # The superseded card takes no answer; the one asked again does.
    assert answer(client, card["id"], "Go on").status_code == 409
    say(client, again, "Go on")  # (unchanged since this card: the recipe goes on)

    ready = asked(until(client, cid, lambda s: asked(s) and "Ready for you" in asked(s)["question"]))
    say(client, ready, "Take in")
    wait_run(client, cid, run_id)
    assert (project_dir / "spec.md").read_text() == "v2\n"


def test_the_digest_binds_what_the_steps_line_changed_in_the_project_bytes_too(
    make_client, project_dir
):
    """No recipe copy: the files as the project holds them, whatever their bytes - of the step's
    agent and of the agent it opened, not of another."""
    client, _ = make_client([])
    runner = client.app.state.runner
    with runner._factory() as s:
        s.add(Conversation(id="c"))
        s.flush()
        s.add(Run(id="r", conversation_id="c", status="running"))
        s.flush()
        s.add_all([Agent(id="lead", run_id="r", role_name="Lead", tools=[]),
                   Agent(id="spec", run_id="r", role_name="Spec writer", tools=[], depth=1,
                         parent_agent_id="lead"),
                   Agent(id="helper", run_id="r", role_name="Coder", tools=[], depth=2,
                         parent_agent_id="spec"),
                   Agent(id="other", run_id="r", role_name="Coder", tools=[], depth=1,
                         parent_agent_id="lead")])
        s.flush()
        s.add_all([FileChange(run_id="r", agent_id=agent, path=path, kind="create",
                              after_content="", after_sha="0" * 64, status="applied")
                   for agent, path in (("spec", "a.md"), ("helper", "b.bin"), ("other", "c.md"))])
        s.commit()
    (project_dir / "a.md").write_bytes(b"spec\n")
    (project_dir / "b.bin").write_bytes(b"\xff\xfe not utf-8")
    ctx = Ctx(run_id="r", cid="c", root=str(project_dir), agent_id="lead", role="Lead", tools=(),
              depth=0)

    held = runner._work_digest(ctx, ["spec"])
    assert held == {"a.md": hashlib.sha256(b"spec\n").hexdigest(),
                    "b.bin": hashlib.sha256(b"\xff\xfe not utf-8").hexdigest()}
    (project_dir / "b.bin").write_bytes(b"\xff\xfe changed")
    (project_dir / "c.md").write_bytes(b"not the step's\n")
    now = runner._work_digest(ctx, ["spec"])
    assert [path for path in held if held[path] != now[path]] == ["b.bin"] and "c.md" not in now


def test_a_spec_approval_is_asked_again_when_a_command_wrote_a_file_in_the_copy(
    make_client, wait_run, project_dir
):
    # B-143 (live): the Coder wrote the file with PowerShell's AppendAllText - no change on record of
    # it - and the card was not asked again.
    client, _ = make_client({
        "Lead": [spawn("Spec writer", "write the spec", "s1"), text("done"), text("done"), text("done")],
        "Spec writer": [text("the spec")],
    })
    recipe = made(client, "Spec first", graph(
        [part("spec", "Write the spec", {"role": "Spec writer"}, ask_me=True),
         part("build", "Build it", {"role": "Coder"})],
        [("start", "spec"), ("spec", "build"), ("build", "end")]))
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], recipe))
    card = asked(until(client, cid, asked))
    runner = client.app.state.runner
    copy = runner._copies[runner._recipe_copy[run_id]]
    (copy.root / "spec.md").write_text("as a command wrote it\n")  # (no FileChange row)
    say(client, card, "Go on")
    again = asked(until(client, cid, lambda s: (a := asked(s)) and a["id"] != card["id"]))
    assert again["question"] == CHANGED_SINCE.format(files="spec.md") + card["question"]
    say(client, again, "Stop")
    wait_run(client, cid, run_id)


def test_in_the_shared_copy_the_digest_leaves_out_what_another_rows_agents_wrote(make_client, project_dir):
    # (The review of B-143, S4: the copy is every team's - another team's writes kept superseding a Go on.)
    from types import SimpleNamespace

    from app.workspace import Workspace
    client, _ = make_client([])
    runner = client.app.state.runner
    with runner._factory() as s:
        s.add(Conversation(id="c"))
        s.flush()
        s.add(Run(id="r", conversation_id="c", status="running"))
        s.flush()
        s.add_all([Agent(id="lead", run_id="r", role_name="Lead", tools=[]),
                   Agent(id="spec", run_id="r", role_name="Spec writer", tools=[], depth=1, parent_agent_id="lead"),
                   Agent(id="docs", run_id="r", role_name="Docs writer", tools=[], depth=1, parent_agent_id="lead")])
        s.flush()
        s.add(FileChange(run_id="r", agent_id="docs", path="README.md", kind="create", after_content="",
                         after_sha="0" * 64, status="in_copy"))
        s.commit()
    for name in ("README.md", "spec.md"):
        (project_dir / name).write_text(name)
    copy = SimpleNamespace(changes=lambda: [("README.md", "new", "ready"), ("spec.md", "new", "ready")],
                           workspace=lambda: Workspace(str(project_dir)))
    runner._copies["lead"], runner._recipe_copy["r"] = copy, "lead"
    ctx = Ctx(run_id="r", cid="c", root=str(project_dir), agent_id="lead", role="Lead", tools=(), depth=0)
    try:
        assert list(runner._work_digest(ctx, ["spec"])) == ["spec.md"]  # (a command's file, on no record: the step's)
    finally:
        runner._copies.pop("lead"), runner._recipe_copy.pop("r")
