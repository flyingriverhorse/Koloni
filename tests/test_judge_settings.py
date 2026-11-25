"""Full auto's judge, its record and settings (0.1.9): a project's switch, on by default; the user's
Judge model, chosen from what may be asked now (`/api/judge`); a judge's card counted as its own
family; the lines not asked about again gone with their project; and the check of the user's words
(K-yargıç) asking the chosen model too."""

import pytest
from sqlalchemy import select

from app import cards
from app.config import load_settings
from app.db.models import JudgeAllowed, OwnRequest
from app.main import create_app
from tests.fakes import ScriptedModel
from tests.keyed import NO_ORIGIN, OWN, TestClient
from tests.test_agent_commands import cmd
from tests.test_chat_flow import text
from tests.test_judge_pick import provider
from tests.test_judge_scenarios import RULE, begin, carded, verdict_line


def test_a_project_has_the_judge_on_until_the_user_turns_it_off(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.get(f"/api/projects/{pid}").json()["full_auto_judge"] is True
    off = {"full_auto_judge": False}
    assert client.patch(f"/api/projects/{pid}", json=off, headers=NO_ORIGIN).status_code == 403
    assert (
        client.patch(f"/api/projects/{pid}", json=off, headers=OWN).json()["full_auto_judge"]
        is False
    )
    assert client.get(f"/api/projects/{pid}").json()["full_auto_judge"] is False


def test_the_judge_model_is_the_fast_tiers_first_until_the_user_chooses(client):
    assert client.get("/api/judge").json() == {
        "provider_id": None,
        "model_id": None,
        "now": None,
        "choices": [],
    }
    fast = provider(client, "Fast", [{"name": "quick", "tier": "fast"}])
    big = provider(client, "Big", [{"name": "deep", "tier": "balanced"}, {"name": "plain"}])
    first = {"provider_id": fast["id"], "provider_name": "Fast", "model_id": "quick", "cli": False}
    deep = {"provider_id": big["id"], "provider_name": "Big", "model_id": "deep", "cli": False}
    said = client.get("/api/judge").json()
    assert said["now"] == first and said["provider_id"] is None
    assert said["choices"] == [{**first, "tier": "fast"}, {**deep, "tier": "balanced"}]
    chosen = {"provider_id": big["id"], "model_id": "deep"}
    # (the user's alone, and only of what is listed)
    assert client.put("/api/judge", json=chosen, headers=NO_ORIGIN).status_code == 403
    for wrong in ({**chosen, "model_id": "plain"}, {"provider_id": big["id"], "model_id": None}):
        assert client.put("/api/judge", json=wrong, headers=OWN).status_code == 422
    said = client.put("/api/judge", json=chosen, headers=OWN).json()
    assert (said["provider_id"], said["model_id"], said["now"]) == (big["id"], "deep", deep)
    # Review Focus 5: its provider closed to agents - the Fast tier's first, and the screen says so
    assert client.patch(
        f"/api/providers/{big['id']}", json={"for_agents": False}, headers=OWN
    ).is_success
    said = client.get("/api/judge").json()
    assert said["provider_id"] == big["id"] and said["now"] == first
    none = client.put("/api/judge", json={"provider_id": None, "model_id": None}, headers=OWN)
    assert none.json()["provider_id"] is None and none.json()["now"] == first
    # (the user's preferences untouched by it)
    assert client.get("/api/preferences").json()["text"] is None


def test_a_judges_card_is_a_family_of_its_own():
    why = "KOLONİ's judge: it sends .env to a server."
    assert cards.card_reason("python gen.py", False, why) == "judge"
    assert "judge" in cards.REASONS
    assert cards.family("KOLONİ's judge said fine") == "other"  # (its card's line alone)


def test_the_lines_not_asked_again_go_with_their_project(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    with client.app.state.session_factory() as session:
        session.add(JudgeAllowed(project_id=pid, command="python gen.py", cwd=".", program_sha=""))
        session.commit()
    assert client.delete(f"/api/projects/{pid}", headers=OWN).status_code == 204
    with client.app.state.session_factory() as session:
        assert session.scalars(select(JudgeAllowed)).all() == []


@pytest.mark.no_po
def test_the_check_of_the_users_words_asks_the_chosen_model(settings_env, wait_run, project_dir):
    lead = ScriptedModel([cmd("rm -rf build"), text("left it")])
    quick = ScriptedModel([], model_id="quick")
    deep = ScriptedModel([verdict_line("ask", why="No line.")], model_id="deep")
    app = create_app(load_settings(settings_env), model=lead, clients={"Fast": quick, "Big": deep})
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        provider(client, "Fast", [{"name": "quick", "tier": "fast"}])
        big = provider(client, "Big", [{"name": "deep", "tier": "strongest"}])
        chosen = {"provider_id": big["id"], "model_id": "deep"}
        assert client.put("/api/judge", json=chosen, headers=OWN).status_code == 200
        _, cid, run_id = begin(client, project_dir, "tidy up", rules=RULE)
        carded(client, cid, run_id, wait_run)
        assert quick.calls == [] and len(deep.calls) == 1
        with client.app.state.session_factory() as session:
            (own,) = session.scalars(select(OwnRequest).where(OwnRequest.run_id == run_id)).all()
            assert (own.provider_name, own.model_id) == ("Big", "deep")
