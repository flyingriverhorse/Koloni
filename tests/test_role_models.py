"""K-rol-model-sirasi: a role's ordered list of preferred models - "first X, then Y" - tried
before its own model and its tier, each passed over as a tier's model is; a sub-agent whose
first choice fails before its first word moves to the next of the list."""

import pytest

from app.db.models import Role
from app.model_client import ModelUnavailable
from app.team import would_run
from tests.test_agents_teams_scenarios import patch_role, spawn
from tests.test_chat_flow import text
from tests.test_spawn import begin, reported, role_id, step
from tests.test_team import team  # noqa: F401  (a fixture)
from tests.test_tier_order_scenarios import both_strongest
from tests.test_tier_scenarios import role_tier


def table(client, role):
    rows = {row["role"]: row for row in client.get("/api/roles/models").json()}
    return rows[role]["provider_name"], rows[role]["model_id"], rows[role]["source"], rows[role]["moved"]


def local_over_its_limit(client, local):
    """The Lead spent 10.50 USD on Local today; its limit is 5 a day."""
    client.put("/api/prices", json={"model_id": "big-model", "input": 3, "output": 15,
                                    "currency": "USD"})
    assert client.patch(f"/api/providers/{local}", json={"day_limit": 5}).status_code == 200


OVER = "over Local's limit of 5.00 USD a day (10.50 spent today)"


def test_the_list_is_saved_in_order_once_each_and_held_to_known_providers_and_five(team):  # noqa: F811
    client, _default, _fast = team([])
    local, fast = both_strongest(team, client)
    saved = patch_role(client, "Reviewer", models=[
        {"provider_id": local, "model_id": " big-model "}, {"provider_id": fast, "model_id": "deep"},
        {"provider_id": local, "model_id": "big-model"}])
    assert saved.status_code == 200, saved.text
    assert saved.json()["models"] == [{"provider_id": local, "model_id": "big-model"},
                                      {"provider_id": fast, "model_id": "deep"}]
    assert patch_role(client, "Reviewer", models=[{"provider_id": "nowhere", "model_id": "x"}]
                      ).status_code == 422
    assert patch_role(client, "Reviewer", models=[{"provider_id": local, "model_id": ""}]
                      ).status_code == 422
    assert patch_role(client, "Reviewer", models=[{"provider_id": local, "model_id": "a\nb"}]
                      ).status_code == 422
    assert patch_role(client, "Reviewer", models=[
        {"provider_id": local, "model_id": f"m{i}"} for i in range(6)]).status_code == 422
    # Empty is no list: the tier's ladder decides, as before.
    role_tier(client, "Reviewer", "strongest")
    assert patch_role(client, "Reviewer", models=[]).json()["models"] is None
    assert table(client, "Reviewer") == ("Local", "big-model", "tier", None)


def test_a_provider_not_used_for_sub_agents_is_not_saved_in_the_list(team):  # noqa: F811
    # B-330: the editor offers the team guide's providers only; the API holds to that too.
    client, _default, _fast = team([])
    paid = team.providers["Paid Api"]["id"]
    answer = patch_role(client, "Reviewer", models=[{"provider_id": paid, "model_id": "gold"}])
    assert answer.status_code == 422, answer.text
    assert answer.json()["detail"] == "a provider of the list is not used for sub-agents"


def test_the_list_is_tried_in_order_and_one_past_its_limit_gives_the_next_of_the_list(
    team, wait_run, project_dir,  # noqa: F811
):
    client, _default, _fast = team(
        [text("a", 1_000_000, 500_000), step(spawn("Reviewer")), text("done")], [text("looked")])
    local, fast = both_strongest(team, client)
    role_tier(client, "Reviewer", "fast")  # (the ladder would say Fast quick)
    assert patch_role(client, "Reviewer", models=[
        {"provider_id": fast, "model_id": "deep"}, {"provider_id": local, "model_id": "big-model"},
    ]).status_code == 200
    assert table(client, "Reviewer") == ("Fast", "deep", "role", None)
    assert patch_role(client, "Reviewer", models=[
        {"provider_id": local, "model_id": "big-model"}, {"provider_id": fast, "model_id": "deep"},
    ]).status_code == 200
    cid, run_id = begin(client, project_dir)
    wait_run(client, cid, run_id)
    assert table(client, "Reviewer") == ("Local", "big-model", "role", None)
    local_over_its_limit(client, local)
    assert table(client, "Reviewer") == ("Fast", "deep", "role", f"{OVER}: the role's 2nd choice")
    # A tier the Lead gives the job wins over the list, as a chosen model does.
    with client.app.state.session_factory() as session:
        would = would_run(session, session.get_one(Role, role_id(client, "Reviewer")), None,
                          tier="fast")
        assert (would.provider.name, would.model_id, would.source) == ("Fast", "quick", "tier")


def test_after_the_list_comes_the_roles_own_model_and_a_provider_gone_from_the_guide_is_said(
    team, wait_run, project_dir,  # noqa: F811
):
    client, _default, _fast = team(
        [text("a", 1_000_000, 500_000), step(spawn("Reviewer")), text("done")], [text("looked")])
    local, fast = both_strongest(team, client)
    assert patch_role(client, "Reviewer", provider_id=fast, model_id="quick", models=[
        {"provider_id": local, "model_id": "big-model"}]).status_code == 200
    cid, run_id = begin(client, project_dir)
    wait_run(client, cid, run_id)
    assert table(client, "Reviewer") == ("Local", "big-model", "role", None)
    local_over_its_limit(client, local)
    assert table(client, "Reviewer") == ("Fast", "quick", "role", f"{OVER}: none of the role's models")
    assert client.patch(f"/api/providers/{local}", json={"for_agents": False}).status_code == 200
    assert table(client, "Reviewer") == (
        "Fast", "quick", "role", "a model of the role's list is not in the team guide: none of "
        "the role's models")


@pytest.mark.no_po
def test_a_first_choice_that_fails_before_its_first_word_gives_the_sub_agent_to_the_second(
    team, wait_run, project_dir,  # noqa: F811
):
    client, default, fast = team(
        [step(spawn("Reviewer")), ModelUnavailable("model server returned 503: busy"),
         text("done")], [text("looked")])
    local, fast_id = both_strongest(team, client)
    assert patch_role(client, "Reviewer", models=[
        {"provider_id": local, "model_id": "big-model"}, {"provider_id": fast_id, "model_id": "deep"},
    ]).status_code == 200
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    reviewer = wait_run(client, cid, run_id)["agents"][1]
    moved = ("Reviewer moved from Local to Fast, the role's 2nd choice: model server returned "
             "503: busy.")
    assert (reviewer["provider_name"], reviewer["status"], reviewer["report"],
            reviewer["chosen_why"]) == ("Fast", "completed", "looked", moved)
    assert len(fast.calls) == 1 and reported(default.calls[-1][-1]["content"]).endswith(moved)


def test_a_list_entry_that_is_on_the_ladder_too_is_not_moved_onto_itself(
    team, wait_run, project_dir,  # noqa: F811
):
    client, _default, _fast = team(
        [step(spawn("Reviewer")), ModelUnavailable("model server returned 503: busy"),
         text("done")], [text("looked")])
    local, _fast_id = both_strongest(team, client)  # strongest: Local big-model, then Fast deep
    role_tier(client, "Reviewer", "strongest")
    assert patch_role(client, "Reviewer", models=[{"provider_id": local, "model_id": "big-model"}]
                      ).status_code == 200
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    reviewer = wait_run(client, cid, run_id)["agents"][1]
    assert (reviewer["provider_name"], reviewer["status"], reviewer["chosen_why"]) == (
        "Fast", "completed",
        "Reviewer moved from Local to Fast, the next strongest model: model server returned "
        "503: busy.")


def test_after_the_list_a_failed_sub_agent_moves_onto_the_roles_own_model(
    team, wait_run, project_dir,  # noqa: F811
):
    client, _default, _fast = team(
        [step(spawn("Reviewer")), ModelUnavailable("model server returned 503: busy"),
         text("done")], [text("looked")])
    local, fast_id = both_strongest(team, client)
    assert patch_role(client, "Reviewer", provider_id=fast_id, model_id="quick", models=[
        {"provider_id": local, "model_id": "big-model"}]).status_code == 200
    cid, run_id = begin(client, project_dir, spawn_approval="never")
    reviewer = wait_run(client, cid, run_id)["agents"][1]
    assert (reviewer["provider_name"], reviewer["status"], reviewer["chosen_why"]) == (
        "Fast", "completed",
        "Reviewer moved from Local to Fast, the role's own model: model server returned "
        "503: busy.")


def test_a_list_entry_its_provider_does_not_run_is_passed_over_with_that_said(team):  # noqa: F811
    client, _default, _fast = team([])
    local, fast = both_strongest(team, client)
    assert client.patch(f"/api/providers/{local}", json={"only_listed": True}).status_code == 200
    assert patch_role(client, "Reviewer", models=[
        {"provider_id": local, "model_id": "other"}, {"provider_id": fast, "model_id": "deep"},
    ]).status_code == 200
    assert table(client, "Reviewer") == (
        "Fast", "deep", "role",
        """Local does not run with the model "other" here: the role's 2nd choice""")
