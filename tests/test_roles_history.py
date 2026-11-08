"""0.1.0-ui: the Agents page's History (`/api/roles/history`), counted from the record as it is:
the sub-agents by role, the turns' teams and recipes as each turn kept them (`Run.teams`)."""

from datetime import timedelta

from app.api import roles
from app.db.models import Agent, Run, now


def _row(team: str, status: str, recipe: str = "", agents: tuple[str, ...] = ()) -> dict:
    return {"team_id": f"t-{team}", "recipe_id": None, "picked_by": "user", "why": None,
            "state": {"run_id": "x", "team": team, "recipe": recipe, "status": status,
                      "agents": list(agents)}}


def test_history_counts_roles_teams_and_recipes_and_leaves_the_turns_lead_out(client, monkeypatch):
    cid = client.post("/api/conversations", json={}).json()["id"]
    old = now() - timedelta(days=10)
    with client.app.state.session_factory() as session:
        def turn(at, teams, agents):
            run = Run(conversation_id=cid, status="completed", created_at=at, teams=teams)
            session.add(run)
            session.flush()
            session.add(Agent(id=f"lead-{run.id}", run_id=run.id, role_name="Lead", name="Lead",
                              tools=[], depth=0, status="completed", created_at=at))
            for agent_id, role, status in agents:
                session.add(Agent(id=agent_id, run_id=run.id, role_name=role, name=role,
                                  tools=[], depth=1, status=status, created_at=at))

        turn(now(), [
            _row("Web app", "in", "Feature", agents=("a1", "a2")),
            _row("Docs", "failed"),
            {"team_id": "t-never", "recipe_id": None, "picked_by": "lead", "why": "w", "state": None},
        ], [("a1", "Coder", "completed"), ("a2", "Tester", "failed"), ("a3", "Coder", "running"),
            ("a4", "Coder", "proposed")])
        turn(now(), [_row("Web app", "running", "Feature")], [("a5", "Reviewer", "cancelled")])
        turn(old, [_row("Web app", "done", "Evolve")], [("a6", "Coder", "completed")])
        session.commit()

    week = client.get("/api/roles/history", params={"days": 7}).json()
    counts = lambda rows: {one["name"]: (one["done"], one["failed"], one["running"]) for one in rows}  # noqa: E731
    # done / failed or stopped / in progress; a proposed agent never ran; the Lead is the turn
    assert counts(week["roles"]) == {"Coder": (1, 0, 1), "Tester": (0, 1, 0), "Reviewer": (0, 1, 0)}
    assert week["lead_turns"] == 2
    # a row never run is no run; a team with no recipe is a team run and no recipe run
    assert counts(week["teams"]) == {"Web app": (1, 0, 1), "Docs": (0, 1, 0)}
    assert counts(week["recipes"]) == {"Feature": (1, 0, 1)}
    by_id = {job["id"]: job for job in week["jobs"]}
    assert set(by_id) == {"a1", "a2", "a3", "a5"}
    assert (by_id["a1"]["teams"], by_id["a1"]["recipes"]) == (["Web app"], ["Feature"])
    assert (by_id["a3"]["teams"], by_id["a3"]["recipes"]) == ([], [])
    assert by_id["a1"]["conversation_id"] == cid

    month = client.get("/api/roles/history").json()
    assert month["days"] == 30 and month["lead_turns"] == 3
    assert counts(month["roles"])["Coder"] == (2, 0, 1)
    assert counts(month["recipes"]) == {"Feature": (1, 0, 1), "Evolve": (1, 0, 0)}
    assert client.get("/api/roles/history", params={"days": 31}).status_code == 422

    # the list is the newest few; the counts are of all of them
    monkeypatch.setattr(roles, "HISTORY_JOBS", 2)
    few = client.get("/api/roles/history", params={"days": 7}).json()
    assert few["jobs_limit"] == 2 and len(few["jobs"]) == 2
    assert counts(few["roles"]) == counts(week["roles"]) and few["lead_turns"] == 2
