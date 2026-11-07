"""Slice 53's acceptance set, the backend's part: the user's own slash commands. Written before the
code.

A command the user saves has a name, a line on what it does, a text with `{args}` where what is
typed after it goes, and, if chosen, a role the Lead is asked to hand it to. It belongs to one
project or to all. A name the box already uses (`new`, `room`, `stop`, `model`, `mode`, `plan`) is
refused, as is a second command of the same name where it would be seen. Only from the app's own
page.

Contract: `GET /api/own-commands?project_id=` (the project's and the ones for every project);
`POST /api/own-commands` {name, description, template, role?, project_id?} → 201;
`PATCH` / `DELETE /api/own-commands/{id}`.
"""

import pytest

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def _built(client):
    return "/api/own-commands" in client.app.openapi()["paths"]


@pytest.fixture
def pid(client, project_dir):
    if not _built(client):
        pytest.skip("slice 53 is not built yet")  # written before the code
    return client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]


def make(client, **body):
    return client.post("/api/own-commands", json=body, headers=ORIGIN)


def test_a_command_is_saved_for_a_project_or_for_all(client, pid, project_dir):
    one = make(
        client,
        name="test-yaz",
        description="Write tests for it",
        template="Write tests for {args}",
        project_id=pid,
    )
    assert one.status_code == 201, one.text
    every = make(
        client,
        name="cevir",
        description="Translate",
        template="Translate to Turkish: {args}",
        role="Translator",
    )
    assert every.status_code == 201, every.text
    elsewhere = project_dir.parent / "other"
    elsewhere.mkdir()
    other = client.post("/api/projects", json={"root_path": str(elsewhere)}).json()["id"]

    def names(p):
        listed = client.get("/api/own-commands", params={"project_id": p}).json()
        return sorted(c["name"] for c in listed)

    assert names(pid) == ["cevir", "test-yaz"]
    assert names(other) == ["cevir"]
    assert every.json()["role"] == "Translator"


@pytest.mark.parametrize(
    "name", ["new", "room", "stop", "model", "mode", "plan", "compare", "Stop", "has space", ""]
)
def test_a_name_the_box_uses_or_no_name_is_refused(client, pid, name):
    assert make(client, name=name, description="x", template="x {args}").status_code == 422


def test_the_same_name_twice_where_it_would_be_seen_is_refused(client, pid):
    assert (
        make(client, name="tidy", description="a", template="a", project_id=pid).status_code == 201
    )
    assert make(client, name="tidy", description="b", template="b").status_code == 409
    assert (
        make(client, name="TIDY", description="c", template="c", project_id=pid).status_code == 409
    )


def test_it_is_changed_and_removed_only_from_the_apps_own_page(client, pid):
    assert (
        client.post(
            "/api/own-commands", json={"name": "x1", "description": "", "template": "t"}
        ).status_code
        == 403
    )
    made = make(client, name="x1", description="", template="t").json()
    assert (
        client.patch(f"/api/own-commands/{made['id']}", json={"template": "u"}).status_code == 403
    )
    changed = client.patch(
        f"/api/own-commands/{made['id']}", json={"template": "u {args}"}, headers=ORIGIN
    )
    assert changed.status_code == 200 and changed.json()["template"] == "u {args}"
    assert client.delete(f"/api/own-commands/{made['id']}").status_code == 403
    assert client.delete(f"/api/own-commands/{made['id']}", headers=ORIGIN).status_code == 204
    assert client.get("/api/own-commands", params={"project_id": pid}).json() == []


def test_an_unknown_role_is_refused(client, pid):
    assert make(client, name="r1", description="", template="t", role="Nobody").status_code == 422
