"""Slice 42c's acceptance set, the backend's part: the project's own tree in the Files window.
Written before the code.

The window lists a project's folders one level at a time and shows a file's text, read only.
Nothing outside the project is listed or read, a link is not followed, a secret file (`.env`, a
key) is neither listed nor read, and a file too large or not text says so instead of its content.

Contract:
- `GET /api/projects/{id}/files?path=<folder>` ("" for the root) → `[{name, kind: "dir"|"file", size}]`
- `GET /api/projects/{id}/file?path=<file>` → `{text: str | None, size, binary, too_large}`
- Outside the project, a secret, or a link → 4xx; an unknown project → 404.
"""

import pytest


def _has_routes(client):
    # (An included router is one entry in `app.routes`: its paths are in the OpenAPI schema.)
    return "/api/projects/{project_id}/files" in client.app.openapi()["paths"]


@pytest.fixture
def project(client, project_dir):
    if not _has_routes(client):
        pytest.skip("slice 42c is not built yet")  # written before the code
    (project_dir / "sub").mkdir()
    (project_dir / "sub" / "a.txt").write_text("alpha\n", encoding="utf-8")
    (project_dir / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (project_dir / "id_rsa").write_text("-----BEGIN KEY-----\n", encoding="utf-8")
    (project_dir / "node_modules").mkdir()
    (project_dir / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(64))
    (project_dir / "big.txt").write_text("x" * (300 * 1024), encoding="utf-8")
    return client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]


def listed(client, pid, path=""):
    answer = client.get(f"/api/projects/{pid}/files", params={"path": path})
    assert answer.status_code == 200, answer.text
    return {e["name"]: e for e in answer.json()}


def test_the_root_lists_its_folders_and_files_but_no_secret(client, project):
    found = listed(client, project)
    assert found["sub"]["kind"] == "dir" and found["node_modules"]["kind"] == "dir"
    assert found["hello.py"]["kind"] == "file" and found["hello.py"]["size"] == len(
        b"print('hi')\n"
    )
    assert ".env" not in found and "id_rsa" not in found


def test_a_folder_is_listed_one_level_down(client, project):
    assert set(listed(client, project, "sub")) == {"a.txt"}


def test_a_file_is_read_as_text(client, project):
    answer = client.get(f"/api/projects/{project}/file", params={"path": "sub/a.txt"})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["text"], body["binary"], body["too_large"]) == ("alpha\n", False, False)


def test_a_picture_and_a_large_file_say_so_instead_of_their_content(client, project):
    pic = client.get(f"/api/projects/{project}/file", params={"path": "pic.png"}).json()
    assert pic["binary"] is True and pic["text"] is None
    big = client.get(f"/api/projects/{project}/file", params={"path": "big.txt"}).json()
    assert big["too_large"] is True and big["text"] is None and big["size"] >= 300 * 1024


@pytest.mark.parametrize("path", ["../", "..", "sub/../../", "C:/Windows", "/etc"])
def test_nothing_outside_the_project_is_listed(client, project, path):
    assert client.get(f"/api/projects/{project}/files", params={"path": path}).status_code >= 400


@pytest.mark.parametrize("path", [".env", "id_rsa", "../hello.py", "C:/Windows/win.ini"])
def test_a_secret_or_an_outside_file_is_not_read(client, project, path):
    answer = client.get(f"/api/projects/{project}/file", params={"path": path})
    assert answer.status_code >= 400
    assert "s3cr3t-value" not in answer.text and "BEGIN KEY" not in answer.text


def test_an_unknown_project_is_404(client, project):
    assert client.get("/api/projects/nope/files", params={"path": ""}).status_code == 404
