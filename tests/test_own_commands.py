"""Slice 53's checks beyond the acceptance set: names compared as the menu folds them, and a
change of place or role checked as a new command would be."""

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def test_names_are_compared_folded_and_a_move_is_checked(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]

    def make(**body):
        return client.post("/api/own-commands", json={"template": "t", **body}, headers=ORIGIN)

    assert make(name="çevir", project_id=pid).status_code == 201
    assert make(name="CEVIR").status_code == 409  # the menu could not tell them apart
    other = project_dir.parent / "other"
    other.mkdir()
    elsewhere = client.post("/api/projects", json={"root_path": str(other)}).json()["id"]
    there = make(name="cevir", project_id=elsewhere, role="translator").json()
    assert there["role"] == "Translator"  # the role's own name
    # made global, it would be seen beside the first project's
    moved = client.patch(
        f"/api/own-commands/{there['id']}", json={"project_id": None}, headers=ORIGIN)
    assert moved.status_code == 409
    cleared = client.patch(f"/api/own-commands/{there['id']}", json={"role": None}, headers=ORIGIN)
    assert cleared.json()["role"] is None and cleared.json()["project_id"] == elsewhere
    assert make(name="x", project_id="nope").status_code == 422


def _make(client, **body):
    return client.post("/api/own-commands", json={"template": "t", **body}, headers=ORIGIN)


def test_names_fold_as_the_menu_does(client):
    # (the page's fold: lower case, marks dropped - U+FE0F too - and ß left as it is)
    assert _make(client, name="stop️").status_code == 422
    assert _make(client, name="́").status_code == 422  # nothing left to type
    assert _make(client, name="x").status_code == 201
    assert _make(client, name="x️").status_code == 409
    assert _make(client, name="straße").status_code == 201
    assert _make(client, name="strasse").status_code == 201


def test_a_roles_name_is_refused_but_the_leads(client):
    refused = _make(client, name="CODER")
    assert refused.status_code == 409 and "role" in refused.json()["detail"]
    assert _make(client, name="lead").status_code == 201  # the Lead has no chip


def test_a_blank_text_is_refused_and_a_null_leaves_a_field_as_it_is(client):
    assert _make(client, name="b1", template="  \n ").status_code == 422
    made = _make(client, name="b2", description="d", template="keep {args}").json()
    url = f"/api/own-commands/{made['id']}"
    assert client.patch(url, json={"template": " "}, headers=ORIGIN).status_code == 422
    kept = client.patch(url, json={"name": None, "template": None, "description": None},
                        headers=ORIGIN)
    assert kept.status_code == 200
    assert (kept.json()["name"], kept.json()["template"], kept.json()["description"]) == (
        "b2", "keep {args}", "d")
