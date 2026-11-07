"""Slice 42c beyond its acceptance set: a link in the tree is neither listed nor followed, a
secret's other spellings are secrets too, and a page of the project is previewed by slice 39's
policy - only a kind a page is drawn with."""

import os
import sys
from pathlib import Path

import pytest

from app import project_files, views
from app.workspace import Workspace, is_secret


def _project(client, project_dir):
    return client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]


def test_a_link_is_neither_listed_nor_followed(client, project_dir, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "x.txt").write_text("outside", encoding="utf-8")
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(outside), str(project_dir / "door"))
    else:
        os.symlink(outside, project_dir / "door", target_is_directory=True)
    pid = _project(client, project_dir)
    names = {e["name"] for e in client.get(f"/api/projects/{pid}/files").json()}
    assert "door" not in names and "hello.py" in names
    assert client.get(f"/api/projects/{pid}/files", params={"path": "door"}).status_code == 404
    read = client.get(f"/api/projects/{pid}/file", params={"path": "door/x.txt"})
    assert read.status_code == 404 and "outside" not in read.text


def test_a_secret_by_any_spelling_windows_opens_it_by():
    for name in (".env", ".ENV.", ".env.local", "prod.env", "sub/id_rsa", "a/server.PEM", ".ssh/known",
                 ".git/config", ".GIT\\config", ".git-credentials", "prod.tfvars"):
        assert is_secret(name), name
    for name in ("hello.py", "environment.md", "id_rsa.pub", "keys.py", "tokenizer.py", ".git",
                 "config", "src/config"):
        assert not is_secret(name), name


def test_a_page_is_previewed_by_the_view_policy_and_only_what_a_page_draws_with(client, project_dir):
    (project_dir / "page.html").write_text("<p>hi</p>", encoding="utf-8")
    (project_dir / ".env").write_text("TOKEN=s3cr3t-value", encoding="utf-8")
    pid = _project(client, project_dir)
    page = client.get(f"/api/projects/{pid}/raw/page.html")
    assert page.status_code == 200 and page.text == "<p>hi</p>"
    assert page.headers["content-security-policy"] == views.POLICY
    assert client.get(f"/api/projects/{pid}/raw/hello.py").status_code == 404
    for path in (".env", "../proj/page.html", "C:/Windows/win.ini"):
        answer = client.get(f"/api/projects/{pid}/raw/{path}")
        assert answer.status_code >= 400 and "s3cr3t" not in answer.text


def test_a_place_koloni_never_opens_inside_the_project_is_neither_listed_nor_read(
    client, tmp_path, monkeypatch
):
    # (KOLONİ's own record, put in the project: the project around it is opened, it is not.
    # Not tmp_path itself: it holds the test's home folder, which is no project - slice 86a.)
    around = tmp_path / "around"
    monkeypatch.setenv("KOLONI_RUNTIME_ROOT", str(around / "runtime"))
    (around / "runtime").mkdir(parents=True)
    (around / "runtime" / "koloni.txt").write_text("record", encoding="utf-8")
    (around / "a.txt").write_text("a", encoding="utf-8")
    pid = _project(client, around)
    names = {e["name"] for e in client.get(f"/api/projects/{pid}/files").json()}
    assert "runtime" not in names and "a.txt" in names
    assert client.get(f"/api/projects/{pid}/files", params={"path": "runtime"}).status_code == 404
    read = client.get(f"/api/projects/{pid}/file", params={"path": "runtime/koloni.txt"})
    assert read.status_code == 404 and "record" not in read.text


def _short(path: Path) -> str | None:
    """Its 8.3 short name, as Windows makes one (`ENV~1` for `.env`); None where none is made."""
    if sys.platform != "win32":
        return None
    import ctypes

    buffer = ctypes.create_unicode_buffer(1024)
    made = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
    name = Path(buffer.value).name if made else ""
    return name if name and name.casefold() != path.name.casefold() else None


def test_a_secret_by_its_short_name_is_neither_listed_read_nor_served(client, project_dir):
    (project_dir / ".env").write_text("TOKEN=s3cr3t-value", encoding="utf-8")
    (project_dir / ".ssh").mkdir()
    (project_dir / ".ssh" / "config").write_text("s3cr3t-value", encoding="utf-8")
    (project_dir / ".env.html").write_text("<p>s3cr3t-value</p>", encoding="utf-8")
    short = {name: _short(project_dir / name) for name in (".env", ".ssh", ".env.html")}
    if None in short.values():
        pytest.skip("this volume makes no 8.3 short names")
    pid = _project(client, project_dir)
    asked = [
        ("file", short[".env"]), ("file", f"{short['.ssh']}/config"), ("files", short[".ssh"]),
        ("file", short[".env.html"]),
    ]
    for how, path in asked:
        answer = client.get(f"/api/projects/{pid}/{how}", params={"path": path})
        assert answer.status_code == 404 and "s3cr3t" not in answer.text, (how, path)
    for path in (short[".env.html"], short[".env"], f"{short['.ssh']}/config"):
        answer = client.get(f"/api/projects/{pid}/raw/{path}")
        assert answer.status_code == 404 and "s3cr3t" not in answer.text, path
    # slice 39's pages too: a name beside a page is read by the same rule
    with pytest.raises(views.Refused):
        views.read_file(Workspace(project_dir), short[".env.html"])


def test_a_folder_lists_its_first_2000_entries(tmp_path):
    for n in range(2100):
        (tmp_path / f"f{n:04}.txt").touch()
    assert len(project_files.listing(str(tmp_path), "")) == 2000
