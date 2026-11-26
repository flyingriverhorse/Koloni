"""0.1.10 (the user's, 26 Nov): Checked keeps the tests and code style on; Pages (KOLONİ's browser
at three widths) and A test for the change are off unless a project ticks them in Check by kind of
work - a project that never changed them has them off, one ticked on keeps them."""

import pytest

from app import proof
from app.db.models import Conversation, Project
from app.db.session import make_engine, make_session_factory, upgrade_db
from tests.keyed import OWN


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "checked.db"
    upgrade_db(path)
    engine = make_engine(path)
    yield make_session_factory(engine)
    engine.dispose()


def checks(db, after_change="check", **kinds):
    with db() as session:
        session.add(
            Project(
                id="p", name="p", root_path="C:/p", after_change=after_change, check_kinds=kinds
            )
        )
        session.flush()
        session.add(Conversation(id="c", project_id="p", title="c"))
        session.commit()
        return proof.checks_of(session, session.get_one(Conversation, "c"))


def test_a_project_that_never_changed_them_has_pages_and_the_test_ask_off(db):
    found = checks(db)
    assert {"tests", "review", "style", "config", "scripts", "docs"} <= found.on
    assert "ui" not in found.on and found.ask_test is False


def test_a_project_that_ticked_them_keeps_them(db):
    found = checks(db, ui=True, test=True)
    assert "ui" in found.on and found.ask_test is True


def test_the_test_ask_follows_the_tests_pages_follow_test_and_review(db):
    found = checks(db, "tests", ui=True, test=True)
    assert found.on == {"tests"} and found.ask_test is True
    with db() as session:
        session.get_one(Project, "p").after_change = "nothing"
        session.commit()
        nothing = proof.checks_of(session, session.get_one(Conversation, "c"))
    assert not nothing.on and nothing.ask_test is False


def test_a_held_turns_ask_stays_with_its_fix(db):
    held = checks(db, test=True)
    assert proof.with_held(held._replace(ask_test=False), held).ask_test is True


def test_the_box_is_saved_from_the_apps_own_page(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    url = f"/api/projects/{pid}"
    assert client.patch(url, json={"check_kinds": {"test": True}}).status_code == 403
    saved = client.patch(url, json={"check_kinds": {"test": True}}, headers=OWN)
    assert saved.status_code == 200 and saved.json()["check_kinds"] == {"test": True}
    assert client.patch(url, json={"check_kinds": {"nope": True}}, headers=OWN).status_code == 422
