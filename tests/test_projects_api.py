import hashlib

from app.config import REPO_ROOT
from app.executors.host import shell_name, store_pwsh_note

OWN = {"Origin": "http://127.0.0.1:8790"}  # as the app's own page says where it is from


def test_create_and_list_project(client, project_dir):
    r = client.post("/api/projects", json={"root_path": str(project_dir)})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "proj" and body["root_path"] == str(project_dir.resolve())
    assert [p["id"] for p in client.get("/api/projects").json()] == [body["id"]]


def test_rejects_missing_folder(client, tmp_path):
    r = client.post("/api/projects", json={"root_path": str(tmp_path / "nope")})
    assert r.status_code == 422
    assert "not an existing folder" in r.json()["detail"]


def test_same_folder_returns_existing(client, project_dir):
    a = client.post("/api/projects", json={"root_path": str(project_dir)}).json()
    b = client.post("/api/projects", json={"root_path": str(project_dir)})
    assert b.status_code == 200 and b.json()["id"] == a["id"]


def test_foreign_origin_is_rejected(client, project_dir):
    r = client.post("/api/projects", json={"root_path": str(project_dir)},
                    headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_health_reports_unreachable_model(client):
    body = client.get("/api/health").json()
    assert body["model_reachable"] is False and body["model_id"] is None
    assert body["tools_supported"] is None and body["error"]
    assert body["model_base_url"] == "http://127.0.0.1:9/v1"
    # the API of the code it runs, as the page's build hashes it (vite.config.ts)
    typed = (REPO_ROOT / "frontend" / "src" / "api" / "generated.ts").read_bytes()
    assert body["api_hash"] == hashlib.sha256(typed.replace(b"\r\n", b"\n")).hexdigest()[:12]
    # the shell its commands run in, as the Commands settings say it (K-pwsh)
    assert body["shell"] == shell_name() and body["shell_note"] == store_pwsh_note()


def test_health_shows_no_password_or_key_of_the_address(client):
    local = client.get("/api/providers").json()[0]
    r = client.patch(f"/api/providers/{local['id']}", json={"base_url": "http://user:s3cret@127.0.0.1:9/v1?key=k2#f"}, headers=OWN)
    assert r.status_code == 200
    body = client.get("/api/health").json()
    assert body["model_reachable"] is False
    assert body["model_base_url"] == "http://127.0.0.1:9/v1"
    assert not any(secret in body["error"] for secret in ("s3cret", "user", "k2"))


def test_project_execution_settings(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    created = client.get("/api/projects").json()[0]
    assert (created["exec_location"], created["docker_image"], created["docker_network"]) == (
        "host", None, False)

    no_image = client.patch(f"/api/projects/{pid}", json={"exec_location": "docker"})
    assert no_image.status_code == 422 and "choose a Docker image first" in no_image.json()["detail"]

    docker = client.patch(f"/api/projects/{pid}", json={
        "exec_location": "docker", "docker_image": " python:3.12 ", "docker_network": True})
    assert docker.status_code == 200
    assert (docker.json()["exec_location"], docker.json()["docker_image"]) == ("docker", "python:3.12")
    assert docker.json()["docker_network"] is True

    assert client.patch(f"/api/projects/{pid}", json={"exec_location": "moon"}).status_code == 422
    assert client.patch("/api/projects/nope", json={"exec_location": "host"}).status_code == 404
    back = client.patch(f"/api/projects/{pid}", json={"exec_location": "host"})
    assert back.json()["exec_location"] == "host" and back.json()["docker_image"] == "python:3.12"


def test_permission_levels(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    conv = client.post(f"/api/projects/{pid}/conversations").json()
    assert conv["permission_mode"] == "ask"
    at = f"/api/conversations/{conv['id']}"

    def now():
        kept = client.get(at).json()["conversation"]
        return kept["permission_mode"], kept["title"]

    # A level raised is leave given - at full auto nothing is asked about - so only the
    # app's own page gives it: a command an agent runs against the app's address says no
    # Origin. Nothing of a request that is refused is kept.
    before = "ask"
    for raised in ("auto_edit", "full_auto"):
        for said in ({}, {"Origin": ""}, {"Origin": "http://evil.example"}):
            refused = client.patch(
                at, json={"permission_mode": raised, "title": "raised"}, headers=said)
            assert refused.status_code == 403 and now() == (before, conv["title"]), (raised, said)
        patched = client.patch(at, json={"permission_mode": raised}, headers=OWN)
        assert patched.status_code == 200 and patched.json()["permission_mode"] == raised
        # the level it is at is no raise
        assert client.patch(at, json={"permission_mode": raised}).status_code == 200
        before = raised
    # ...and lowering it needs nothing more than any other setting
    for lowered in ("auto_edit", "ask"):
        assert client.patch(at, json={"permission_mode": lowered}).json()[
            "permission_mode"] == lowered
    assert client.patch(at, json={"permission_mode": "yolo"}).status_code == 422
