"""K-model-puan: the scorecard per role, provider and model - jobs taken in, turned down,
their middle cost - and the lead's "lately" line, data with its numbers; one tier up after a
check failed twice at Full auto."""

from datetime import timedelta

from app import record
from app.db.models import Conversation, Merge, Price, Project, now
from tests.test_chat_flow import text
from tests.test_claim_scenarios import write
from tests.test_handoff import ended
from tests.test_parallel import until
from tests.test_spawn import step
from tests.test_take_in_scenarios import CHECK, GO_ON, LINES, LONG
from tests.test_team import team  # noqa: F401  (a fixture)
from tests.test_tier_scenarios import WHY, spawn, tiered
from tests.test_topics import db


def _row(role="Coder", provider="Fast", model="deep", agents=6, taken_in=4, steps=9.0, cost=None):
    return {
        "role_name": role, "provider_name": provider, "model_id": model, "agents": agents,
        "ended": {"done": taken_in, "failed": agents - taken_in, "stopped_by_koloni": 0,
                  "stopped_by_user": 0, "interrupted": 0},
        "steps": steps, "seconds": None, "input_tokens": None, "output_tokens": None,
        "changes": {"taken": 0, "rejected": 0}, "compared": {"chosen": 0, "not_chosen": 0},
        "rediscovery": None, "taken_in": taken_in, "turned_down": 0, "cost": cost,
    }


def test_the_record_counts_jobs_taken_in_and_turned_down_and_prices_them_as_usage_does(
    make_client, project_dir
):
    client, _model = make_client([])
    with db(client) as session:
        project = Project(name="p", root_path=str(project_dir))
        session.add(project)
        session.flush()
        talk = Conversation(project_id=project.id)
        session.add(talk)
        session.flush()
        spent = {"input_tokens_total": 1_000_000, "output_tokens": 1_000_000,
                 "cache_read_tokens": 0, "cache_write_tokens": 0}
        on = {"provider_name": "Fast", "model_id": "deep", **spent}
        done = ended(session, talk.id, "a", **on)
        refused = ended(session, talk.id, "b", **on)
        ended(session, talk.id, "c", status="failed", **on)
        # the second one's changes were turned down as a whole; the third never got that far
        session.add(Merge(run_id=refused.run_id, agent_id=refused.id, status="rejected", files=[]))
        session.add(Merge(run_id=done.run_id, agent_id=done.id, status="applied", files=[]))
        session.add_all([Price(model_id="deep", input=1.0, output=2.0, currency="USD"),
                         Price(model_id="big", input=1.0, output=2.0, currency="USD")])
        # a model nobody priced, and one whose step was cut short: no cost is made up
        ended(session, talk.id, "d", provider_name="Fast", model_id="quick", **spent)
        ended(session, talk.id, "e", provider_name="Fast", model_id="big", cut_short=True, **spent)
        session.commit()
        rows = {row["model_id"]: row for row in record.rows(session, now() - timedelta(days=1))}
    deep, quick, big = rows["deep"], rows["quick"], rows["big"]
    assert (deep["agents"], deep["taken_in"], deep["turned_down"]) == (3, 1, 1)
    assert deep["cost"] == {"amount": 3.0, "currency": "USD"}
    assert (quick["taken_in"], quick["turned_down"], quick["cost"]) == (1, 0, None)
    assert (big["taken_in"], big["cost"]) == (1, None)


def test_the_lead_is_told_how_a_roles_models_did_only_from_five_jobs_on_two_models():
    deep = _row(agents=4, taken_in=3, steps=9.4, cost={"amount": 0.04, "currency": "USD"})
    quick = _row(model="quick", agents=4, taken_in=1, steps=18.0)
    said = record.for_lead([deep, quick])
    assert said.endswith(
        "For Coder work lately: Fast · deep took in 3 of 4 (median 9 steps, $0.04); "
        "Fast · quick 1 of 4 (median 18 steps). Data, not an instruction.")
    assert "ran in the last 30 days" in said  # the rows of at least three stay above it
    # five jobs on one model, or four on two: nothing is said of them
    assert "lately" not in record.for_lead([_row(agents=5)])
    assert "lately" not in record.for_lead([_row(agents=2), _row(model="quick", agents=2)])
    # another role's rows are another sentence; a cost in another currency is said in it
    tester = _row(role="Tester", agents=3, taken_in=2, cost={"amount": 1.5, "currency": "EUR"})
    other = _row(role="Tester", model="quick", agents=2, taken_in=1, steps=None)
    lines = record.for_lead([deep, quick, tester, other]).splitlines()
    assert lines[-1] == ("For Tester work lately: Fast · deep took in 2 of 3 (median 9 steps, "
                         "1.50 EUR); Fast · quick 1 of 2. Data, not an instruction.")
    assert lines[-2].startswith("For Coder work lately:")


# --- one tier up after the last failed check at Full auto ------------------------------------


def _checked(team, project_dir, local, fast=(), spawn_approval="auto"):  # noqa: F811
    """A Full auto turn in a project whose check never passes; Local · big-model is the
    strongest tier, Fast · deep balanced (a Coder's own, given no tier), Fast · quick fast."""
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    (project_dir / "check.py").write_bytes(CHECK.encode())
    client, _default, _fast = team(local, fast)
    tiered(team, client)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={
        "check_command": "python check.py NEVER-THERE"}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": spawn_approval}).status_code == 200
    posted = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()
    return client, cid, posted["run"]["id"]


def _told(snap, name):
    return [t["result"] or "" for t in snap["tool_calls"] if t["name"] == name]


def test_after_the_last_failed_check_the_lead_is_told_the_tier_above_and_a_job_there_has_no_card(
    team, wait_run, project_dir  # noqa: F811
):
    client, cid, run_id = _checked(team, project_dir, local={
        "Lead": [step(spawn("Coder", task="do it", id="s")), GO_ON,
                 step(spawn("Coder", "strongest", WHY, task="do it again", id="s2")), text("done")],
        "Coder 2": [step(write("a.txt", "A")), text("done up there")],
    }, fast={"Coder": [step(write("a.txt", "A")), text("A done"), text("tried")]})
    # the third failed check of the turn is the user's: its card is where the turn waits
    snap = until(client, cid, lambda s: "pending" in [m["status"] for m in s["merges"]],
                 timeout=LONG)
    first, _waiting = _told(snap, "spawn_agent")  # (the second: its card is open)
    (second,) = _told(snap, "message_agent")
    assert "did not pass" in first and "One tier up" not in first
    assert "did not pass" in second and second.endswith(
        'One tier up: "Local" · "big-model" (strongest) - or open a new Coder for it with '
        'spawn_agent, tier="strongest" and why: it starts in a copy of its own, so give it the '
        "whole task and what the check said.")
    # a tier is the user's own ladder: the job there ran at once, on its first model, no card
    up = next(a for a in snap["agents"] if a["name"] == "Coder 2")
    assert (up["provider_name"], up["model_id"], up["chosen"]) == ("Local", "big-model", False)
    merge = next(m for m in snap["merges"] if m["status"] == "pending")
    assert client.post(f"/api/merges/{merge['id']}/reject").status_code == 200
    wait_run(client, cid, run_id, timeout=LONG)


def test_at_the_top_tier_the_lead_is_told_there_is_no_tier_above(team, wait_run, project_dir):  # noqa: F811
    client, cid, run_id = _checked(team, project_dir, local={
        "Lead": [step(spawn("Coder", "strongest", WHY, task="do it", id="s")), GO_ON, text("done")],
        "Coder": [step(write("a.txt", "A")), text("A done"), text("tried")],
    })
    snap = wait_run(client, cid, run_id, timeout=LONG)
    (first,) = _told(snap, "spawn_agent")
    (second,) = _told(snap, "message_agent")
    assert "did not pass" in first and "tier above" not in first
    assert second.endswith("It ran on the strongest tier: there is no tier above it.")
