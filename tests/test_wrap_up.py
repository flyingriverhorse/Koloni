"""K-toparla: an agent near its limit of steps or of tokens is told so before its step, so
that it can end its work and write its report rather than be cut off in the middle."""

from tests.test_model_choice import ORIGIN, looks
from tests.test_spawn import begin, role_id, spawn


def last(request):
    return request[-1]["content"] if request[-1]["role"] == "user" else ""


def test_the_last_steps_of_a_roles_limit_are_said_before_they_are_taken(
    make_client, wait_run, project_dir
):
    client, model = make_client([looks(1), looks(2), looks(3), looks(4)])
    client.headers["Origin"] = ORIGIN
    client.patch(f"/api/roles/{role_id(client, 'Lead')}", json={"max_steps": 3})
    cid, run_id = begin(client, project_dir, mode="full_auto")
    wait_run(client, cid, run_id)
    told = [last(request) for request in model.calls]
    assert len(told) == 3 and "left" not in told[0]
    assert "2 steps left" in told[1] and "1 step left" in told[2]
    assert "write your report" in told[2]


def test_an_agent_near_its_roles_tokens_is_told_how_far_it_has_gone(
    make_client, wait_run, project_dir
):
    client, model = make_client({"Lead": [spawn("Coder"), looks(9)], "Coder": [looks(1), looks(2)]})
    client.headers["Origin"] = ORIGIN
    client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"max_tokens": 7})
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    wait_run(client, cid, run_id)
    first, second = (last(request) for request in model.calls_of["Coder"])
    assert "tokens" not in first
    assert "7 of the 7 tokens" in second and "write your report" in second
