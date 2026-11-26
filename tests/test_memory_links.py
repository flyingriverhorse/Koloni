"""22c: another project's memory, read only - optional. (0.1.10: the search by meaning is cut.)"""

import pytest
from sqlalchemy import select

from app import earlier
from app import memory as kept
from app.db.models import Memory, Project
from tests.test_earlier import a_turn

ORIGIN = "http://127.0.0.1:8790"


def note(client, pid, text, about):
    """A note into a project's journal, as an agent's `remember` writes it."""
    with client.app.state.session_factory() as session:
        return kept.keep_note(
            session,
            pid,
            kept.plan_remember({"text": text, "about": about}),
            agent_id="a1",
            run_id="r1",
            conversation_id="c1",
            source=None,
            checked_how=None,
        ).id


def search(client, pid, words):
    got = client.get(f"/api/projects/{pid}/memory/search", params={"q": words})
    assert got.status_code == 200, got.text
    return got.json()


@pytest.fixture
def two(client, project_dir, tmp_path):
    """Two projects of this KOLONİ, A and B; B has a note and a turn about the greeting."""
    client.headers["Origin"] = ORIGIN
    other = tmp_path / "other"
    other.mkdir()
    a = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    b = client.post("/api/projects", json={"root_path": str(other), "name": "Other one"}).json()[
        "id"
    ]
    note(client, b, "the greeting is merhaba", "greeting")
    with client.app.state.session_factory() as session:
        a_turn(
            session, "we said the GREETING-WORD is merhaba", answer="", rid="rb", cid="cb", pid=b
        )
        earlier.index_run(session, "rb")
        session.commit()
    return a, b


def test_a_linked_projects_memory_and_turns_are_found_tagged_and_not_checked(two, client):
    a, b = two
    assert search(client, a, "greeting") == {"memory": [], "turns": []}
    # only another project of this KOLONİ, never itself
    assert client.patch(f"/api/projects/{a}", json={"memory_links": [a]}).status_code == 422
    assert client.patch(f"/api/projects/{a}", json={"memory_links": ["nobody"]}).status_code == 422
    linked = client.patch(f"/api/projects/{a}", json={"memory_links": [b, b]})
    assert linked.status_code == 200 and linked.json()["memory_links"] == [b]
    found = search(client, a, "greeting")
    (record,) = found["memory"]
    assert (record["from_project"], record["source_state"]) == ("Other one", "none")
    assert (
        found["turns"][0]["project"] == "Other one"
        and "GREETING-WORD" in found["turns"][0]["excerpt"]
    )
    # as an agent's recall reads it: tagged with the project, and that nothing was checked here
    with client.app.state.session_factory() as session:
        project = session.get_one(Project, a)
        also = kept.also(session, project)
        said, watched = kept.looked_up(session, project, "greeting", "", also)
        assert (
            'from the project "Other one" - its files are not in this project: it could not be checked here'
            in said
        )
        assert list(watched.values()) == ["none"]
        assert 'in the project "Other one")' in earlier.told(session, a, "greeting", also)
        # nothing of the linked project is given at a start
        assert kept.briefing(session, project, "the greeting")[0] == ""
        # a note written in A goes to A, and B stays as it was
        before = session.scalars(select(Memory.id).where(Memory.project_id == b)).all()
    mine = note(client, a, "the greeting is hello here", "greeting")
    with client.app.state.session_factory() as session:
        assert session.get_one(Memory, mine).project_id == a
        assert session.scalars(select(Memory.id).where(Memory.project_id == b)).all() == before
    # the other way round nothing is linked: B does not see A's note
    assert [r["text"] for r in search(client, b, "greeting")["memory"]] == [
        "the greeting is merhaba"
    ]
    # unlinked, it is not found any more
    client.patch(f"/api/projects/{a}", json={"memory_links": []})
    assert [r["text"] for r in search(client, a, "greeting")["memory"]] == [
        "the greeting is hello here"
    ]
    assert search(client, a, "greeting")["turns"] == []
