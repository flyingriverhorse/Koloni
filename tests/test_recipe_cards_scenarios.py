"""Batch-17: a recipe's cards. G3 (`tasarim/specs/2026-10-25-referans-ikinci-tur.md`): a step whose
provider is at its limit, or signed out, goes on with the same agent - at its reset, or signed in
again - never on another model unasked. The user's Finish now on a looped recipe, and "Who checks?"
where only the role that wrote the work could check it.
"""

from datetime import UTC, datetime, timedelta

import pytest

import app.agent
from app.model_client import ModelUnavailable
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN, teams_of
from tests.test_claim_scenarios import write
from tests.test_parallel import until
from tests.test_recipe_checks_scenarios import build_review_ship
from tests.test_recipe_run_scenarios import (
    FOUND,
    NONE,
    READY,
    answer,
    asked,
    by_call,
    manual,
    one_step,
    row,
)
from tests.test_spawn import begin, call, role_id, spawn, step


def hit(seconds=None, words="model server returned 429: slow down"):
    """A model step at its provider's limit, which resets `seconds` from when it is hit (None: not said)."""
    async def limited(on_delta):
        failed = ModelUnavailable(words)
        if seconds is not None:
            failed.failure = ("rate_limited", datetime.now(UTC) + timedelta(seconds=seconds))
        raise failed
    return limited


def other(card):
    return lambda s: asked(s) is not None and asked(s)["id"] != card["id"]


@pytest.fixture(autouse=True)
def no_margin(monkeypatch):
    # Go on waits five seconds past a reset: real seconds inside these tests' waits, which under
    # load ran out. One is past the few milliseconds the loop's clock and the reset's differ
    # by here (with none, the wait could end just before the reset and offer it again).
    monkeypatch.setattr(app.agent, "RESET_MARGIN", 1)


def test_go_on_at_the_reset_has_the_same_agent_go_on_once_and_a_limit_hit_again_asks_again(
    make_client, wait_run, project_dir
):
    client, model = make_client({"Lead": [spawn("Coder", "build"), text("done")], "Coder": [hit(2), hit()]})
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], one_step(client, "Just build", "Coder")))
    card = asked(until(client, cid, asked))
    go_on = next(word for word in card["options"] if word.startswith("Go on at "))
    assert card["options"] == [go_on, "Skip", "Stop"]
    assert f"{go_on}: the same agent goes on from what it has done so far." in card["question"]
    answer(client, card, go_on)
    # While it waits, its row says till when.
    waiting = until(client, cid, lambda s: (row(s)["why"] or "").startswith("waits till "))
    assert row(waiting)["why"] == f"waits till {go_on.removeprefix('Go on at ')} for Coder's limit"
    # (Its second limit names no reset: nothing to wait for, and a short window's is tried again.)
    again = asked(until(client, cid, other(card), timeout=15))
    assert again["options"] == ["Try again", "Skip", "Stop"]
    agents = client.get(f"/api/conversations/{cid}").json()["agents"]
    assert len(model.calls_of["Coder"]) == 2 and [a["name"] for a in agents if a["depth"]] == ["Coder"]
    # Go on is KOLONİ's own word to it, not a message between agents that counts against the turn's.
    assert model.calls_of["Coder"][1][-1]["content"].startswith("KOLONİ: your provider can be used again")
    snap = client.get(f"/api/conversations/{cid}").json()
    assert row(snap)["why"] is None and not [m for m in snap["messages"] if m["role"] == "agent"]
    answer(client, again, "Stop")
    assert row(wait_run(client, cid, run_id))["status"] == "stopped"


def test_reconnect_has_the_same_agent_go_on_once_signed_in(make_client, wait_run, project_dir):
    client, model = make_client({
        "Lead": [spawn("Coder", "build"), text("done")],
        "Coder": [ModelUnavailable("model server returned 401: invalid api key"), step(write("a.py", "a\n")),
                  text("built")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], one_step(client, "Just build", "Coder")))
    card = asked(until(client, cid, asked))
    assert card["options"] == ["Reconnect", "Skip", "Stop"]
    assert "(not signed in). Sign in to " in card["question"] and "first, then Reconnect." in card["question"]
    answer(client, card, "Reconnect")
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"], timeout=10)
    (coder,) = [a for a in snap["agents"] if a["depth"]]
    assert coder["status"] == "completed" and len(model.calls_of["Coder"]) == 3
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "a.py").exists() and "Coder replied:\n\nbuilt" in by_call(snap)[0][1]
    # Its opener hears it finished: no failure, nor advice to try another provider or tier.
    status, said = by_call(snap)[0]
    assert status == "succeeded" and said.startswith("Coder went on and finished.") and "Why it failed" not in said


def reconnect_at_the_last_step(make_client, project_dir, after, lower_to=None):
    """B-325: a Coder whose role lets it take three steps takes two, and its third is refused by
    its provider (signed out); then - its role's limit lowered to `lower_to`, or left - Reconnect."""
    looks = [step(call("list_dir", {}, f"l{n}")) for n in range(2)]
    client, model = make_client({
        "Lead": [spawn("Coder", "build"), text("done")],
        "Coder": [*looks, ModelUnavailable("model server returned 401: invalid api key"), *after],
    })
    assert client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"max_steps": 3},
                        headers=OWN).status_code == 200
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], one_step(client, "Just build", "Coder")))
    card = asked(until(client, cid, asked))
    assert card["options"] == ["Reconnect", "Skip", "Stop"]
    if lower_to is not None:
        assert client.patch(f"/api/roles/{role_id(client, 'Coder')}", json={"max_steps": lower_to},
                            headers=OWN).status_code == 200
    answer(client, card, "Reconnect")
    return client, model, cid, run_id, card


def test_a_step_its_provider_refused_is_no_step_of_its_roles_limit(make_client, wait_run, project_dir):
    client, model, cid, run_id, _card = reconnect_at_the_last_step(
        make_client, project_dir, [text("built")])
    snap = wait_run(client, cid, run_id)  # (K-r144: it changed no file - no Take in card)
    assert len(model.calls_of["Coder"]) == 4                     # the 401 did not take its third
    status, said = by_call(snap)[0]
    assert status == "succeeded" and said.startswith("Coder went on and finished."), said


def test_reconnect_with_no_step_of_its_role_left_says_so_and_not_the_card_again(
    make_client, wait_run, project_dir
):
    client, model, cid, run_id, card = reconnect_at_the_last_step(
        make_client, project_dir, [text("never said")], lower_to=2)
    def coder(snap):
        return [a for a in snap["agents"] if a["depth"]][0]

    # (its row said why its provider refused it till Reconnect)
    snap = until(client, cid, lambda s: coder(s)["status"] == "failed" and not coder(s)[
        "error"].startswith("model server"), timeout=10)
    assert (coder(snap)["error"], coder(snap)["failure"]) == ("stopped at its role's limit of 2 steps", None)
    assert len(model.calls_of["Coder"]) == 3
    again = asked(snap)
    assert again is None or "Reconnect" not in again["options"], again
    if again is not None:
        answer(client, again, "Stop")
    wait_run(client, cid, run_id)


def test_a_long_window_is_not_waited_for_nor_tried_again(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build"), text("done")],
        "Coder": [hit(3600, "Codex reported an error: You've hit your weekly limit")],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], one_step(client, "Just build", "Coder")))
    card = asked(until(client, cid, asked))
    assert card["options"] == ["Skip", "Stop"] and "(its limit is reached)." in card["question"]
    answer(client, card, "Stop")
    wait_run(client, cid, run_id)


def test_stop_ends_the_wait_for_a_reset_and_the_agent_does_not_go_on(make_client, wait_run, project_dir):
    client, model = make_client({"Lead": [spawn("Coder", "build"), text("done")], "Coder": [hit(3600)]})
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, one_step(client, "Just build", "Coder")))
    card = asked(until(client, cid, asked))
    answer(client, card, next(word for word in card["options"] if word.startswith("Go on at ")))
    assert client.post(f"/api/conversations/{cid}/teams/{web['id']}/stop", headers=OWN).status_code == 200
    snap = wait_run(client, cid, run_id, timeout=10)
    assert row(snap)["status"] == "stopped" and len(model.calls_of["Coder"]) == 1


def test_finish_now_ends_a_loop_at_ready_for_you_with_what_was_found(make_client, wait_run, project_dir, gate):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Reviewer", "review", "r1"),
                 step(call("spawn_agent", {"role": "Coder", "task": "fix", "findings_from": "Reviewer"}, "c2")),
                 text("over to you")],
        "Coder": [step(write("greet.py", "print('Helo')\n")), text("built")],
        "Coder 2": [gate.step(text("fixed"))],
        "Reviewer": [text(FOUND)],
    })
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, build_review_ship(client)))
    finish = f"/api/conversations/{cid}/teams/{web['id']}/finish"
    gate.wait_partial()
    assert client.post(finish).status_code == 403
    assert client.post(finish, headers=OWN).status_code == 200
    gate.release()
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert row(snap)["status"] == "ready"
    assert row(snap)["why"] == "finished by you at its Build it step: what was found so far is left to you"
    answer(client, asked(snap), "Take in")
    snap = wait_run(client, cid, run_id)
    assert (project_dir / "greet.py").exists() and row(snap)["status"] == "in"
    assert "Tester" not in [a["role_name"] for a in snap["agents"]]
    # Only while its recipe runs.
    refused = client.post(finish, headers=OWN)
    assert refused.status_code == 409 and "no turn" in refused.json()["detail"]


def built_then_checked(client):
    """A review drawn by a team whose one role is the Coder, who builds before it: known only as it runs."""
    from tests.test_recipe_run_scenarios import made, pair
    from tests.test_recipes_scenarios import graph
    from tests.test_recipes_scenarios import step as part
    pair(client, None, ("Coder",))
    return made(client, "Build and check", graph(
        [part("build", "Build it", {"role": "Coder"}),
         part("check", "Check it", {"team": "Pair"}, done_when="no_findings")],
        [("start", "build"), ("build", "check"), ("check", "end")]))


def test_who_checks_is_asked_where_only_the_writer_could_and_a_check_role_takes_its_place(
    make_client, wait_run, project_dir
):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Reviewer", "check it", "r1"), text("done")],
        "Coder": [step(write("greet.py", "print('Hello')\n")), text("built")],
        "Reviewer": [text(NONE)],
    })
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, built_then_checked(client)))
    card = asked(until(client, cid, asked))
    assert card["question"].startswith("Web app: Check it: nobody but Coder, who did the work, can check it. Who checks?")
    assert "Reviewer" in card["options"] and "Coder" not in card["options"]
    assert card["options"][-2:] == ["Coder checks it itself", "Stop"] and len(card["options"]) == 6
    assert "Observer" not in card["options"]  # (never opened as an agent)
    answer(client, card, "reviewer")  # (written, not clicked: any check role that is on is taken)
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert [a["role_name"] for a in snap["agents"] if a["depth"]] == ["Coder", "Reviewer"]
    assert "for Reviewer" in by_call(snap)[0][1] and not any(s["own_check"] for s in row(snap)["steps"])
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_at_full_auto_the_lead_picks_who_checks(make_client, wait_run, project_dir):
    """K-fullauto-sorma 2: "Who checks?" is the Lead's at Full auto - a checker, never the writer
    itself nor Stop (those are left off what it is offered)."""
    from tests.test_lead_decides import says
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), says("Reviewer", "A second pair of eyes."),
                 spawn("Reviewer", "check it", "r1"), text("done")],
        "Coder": [step(write("greet.py", "print('Hello')\n")), text("built")],
        "Reviewer": [text(NONE)],
    })
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never", teams_mode="manual",
                        teams=[{"team_id": teams_of(client)["Web app"]["id"],
                                "recipe_id": built_then_checked(client)["id"]}])
    snap = wait_run(client, cid, run_id, timeout=10)
    (card,) = snap["questions"]
    assert "Who checks?" in card["question"]
    assert (card["answer"], card["lead_why"]) == ("Reviewer", "A second pair of eyes.")
    assert [a["role_name"] for a in snap["agents"] if a["depth"]] == ["Coder", "Reviewer"]
    assert row(snap)["status"] == "in" and (project_dir / "greet.py").exists()


def test_the_writer_checks_its_own_work_only_as_the_user_says_and_its_node_says_so(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Coder", "check it", "c2"), text("done")],
        "Coder": [step(write("greet.py", "print('Hello')\n")), text("built")],
        "Coder 2": [text(NONE)],
    })
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], built_then_checked(client)))
    answer(client, asked(until(client, cid, asked)), "Coder checks it itself")
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert [(s["id"], s["own_check"]) for s in row(snap)["steps"]] == [("build", False), ("check", True), ("end", False)]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_a_writer_only_review_fits_nobody_till_the_user_says_who_checks():
    from app import recipe_run
    from tests.test_recipe_checks_scenarios import done, run_of
    from tests.test_recipes_scenarios import graph
    from tests.test_recipes_scenarios import step as part
    state = run_of(graph(
        [part("build", "Build it", {"role": "Coder"}), part("check", "Check it", {"lead": True}, done_when="no_findings")],
        [("start", "build"), ("build", "check"), ("check", "end")]), picks=("Coder",))
    done(state, "Coder")
    assert recipe_run.unchecked(recipe_run.ahead(state)) == [(0, "check", ["Coder"])]
    assert state["at"] == "build"  # (looked ahead, not moved)
    recipe_run.advance(state)
    assert recipe_run.open_to(state) == []
    recipe_run.checks(state, "check", 0, None)
    assert recipe_run.open_to(state) == ["Coder"] and recipe_run.unchecked(state) == []


def test_the_lead_is_told_the_way_on_is_the_steps_role_or_the_users_finish_now_or_stop(
    make_client, wait_run, project_dir
):
    # R56 (live): refused another role, the Lead offered "(c) you approve me making the edit directly"; told
    # "Stop here", it opened a Reviewer all the same.
    client, model = make_client({"Lead": [spawn("Coder", "build"), text("done")], "Coder": [text("built")]})
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], one_step(client, "Just build", "Coder")))
    wait_run(client, cid, run_id)  # (K-r144: it changed no file - no Take in card)
    offered =next(t["function"] for t in model.tool_args[0] if t["function"]["name"] == "spawn_agent")
    assert "the user's Finish now or Stop on the team - never offer the user a way round" in offered["description"]
    assert "When the user says to stop, open no other agent" in offered["description"]


def test_with_no_other_role_on_to_check_it_the_writer_checks_and_its_node_says_so(make_client, wait_run, project_dir):
    client, _model = make_client({
        "Lead": [spawn("Coder", "build", "c1"), spawn("Coder", "check it", "c2"), text("done")],
        "Coder": [step(write("greet.py", "print('Hello')\n")), text("built")],
        "Coder 2": [text(NONE)],
    })
    for role in client.get("/api/roles").json():
        if role["kind"] == "check" and role["name"] != "Observer":  # (always there, never opened)
            assert client.patch(f"/api/roles/{role['id']}", json={"enabled": False}, headers=OWN).status_code == 200
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], built_then_checked(client)))
    snap = until(client, cid, lambda s: asked(s) and READY in asked(s)["question"])
    assert [q["question"] for q in snap["questions"]] == [asked(snap)["question"]]
    assert [s["own_check"] for s in row(snap)["steps"]] == [False, True, False]
    answer(client, asked(snap), "Take in")
    wait_run(client, cid, run_id)


def test_a_limit_still_reached_at_go_ons_time_brings_the_card_back_with_its_next_reset(
    make_client, wait_run, project_dir
):
    client, model = make_client({"Lead": [spawn("Coder", "build"), text("done")], "Coder": [hit(1)]})
    later = datetime.now(UTC) + timedelta(hours=1)
    limits = client.app.state.runner.providers.limits
    limits.last = lambda provider: {"windows": [{"name": None, "minutes": 300, "used_percent": 100,
                                                 "resets_at": later, "stale": False}]}
    web = teams_of(client)["Web app"]
    cid, run_id = manual(client, project_dir, (web, one_step(client, "Just build", "Coder")))
    card = asked(until(client, cid, asked))
    answer(client, card, next(word for word in card["options"] if word.startswith("Go on at ")))
    again = asked(until(client, cid, other(card), timeout=10))
    assert f"Go on at {later.astimezone():%H:%M}" in again["options"] and "Try again" not in again["options"]
    assert len(model.calls_of["Coder"]) == 1
    answer(client, again, "Stop")
    wait_run(client, cid, run_id)


def test_who_checks_names_two_writers_and_stop_stops_the_recipe(make_client, wait_run, project_dir):
    from tests.test_recipe_run_scenarios import made, pair
    from tests.test_recipes_scenarios import graph
    from tests.test_recipes_scenarios import step as part
    client, _model = make_client({
        "Lead": [spawn("Coder", "a", "c1"), spawn("Debugger", "b", "d1"), text("done")],
        "Coder": [text("built a")], "Debugger": [text("built b")],
    })
    pair(client, None)
    recipe = made(client, "Pair builds and checks", graph(
        [part("a", "Build a", {"role": "Coder"}), part("b", "Build b", {"role": "Debugger"}),
         part("check", "Check it", {"team": "Pair"}, done_when="no_findings")],
        [("start", "a"), ("a", "b"), ("b", "check"), ("check", "end")]))
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], recipe))
    card = asked(until(client, cid, asked))
    assert "nobody but Coder and Debugger, who did the work" in card["question"]
    assert card["options"][-2:] == ["Coder and Debugger check it themselves", "Stop"]
    answer(client, card, "Stop")
    assert (row(wait_run(client, cid, run_id))["status"], row(client.get(f"/api/conversations/{cid}").json())["why"]) == (
        "stopped", "Stopped by you")


def test_signed_out_is_reconnected_not_waited_for_whatever_window_is_full(make_client, wait_run, project_dir):
    client, _model = make_client({"Lead": [spawn("Coder", "build"), text("done")],
                                  "Coder": [ModelUnavailable("model server returned 401: invalid api key")]})
    later = datetime.now(UTC) + timedelta(hours=1)
    client.app.state.runner.providers.limits.last = lambda provider: {"windows": [
        {"name": None, "minutes": 300, "used_percent": 100, "resets_at": later, "stale": False}]}
    cid, run_id = manual(client, project_dir, (teams_of(client)["Web app"], one_step(client, "Just build", "Coder")))
    card = asked(until(client, cid, asked))
    assert card["options"] == ["Reconnect", "Skip", "Stop"]
    answer(client, card, "Stop")
    wait_run(client, cid, run_id)
