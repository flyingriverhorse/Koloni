"""Slice 86a's folder browser, and which folders may be opened. Written before the code.

Design: `tasarim/specs/2026-10-23-dilim-86-klasorler-design.md` §2 ("Open a folder…") and §6b.

Contract:
- `POST /api/folders/browse` {path?} (the app's own page only; none: the home folder) ->
  {path, parts, shortcuts, entries: [{name, path, koloni, git, hidden, blocked}], more}.
  Folders only, never a file's name; at most 500, `more` where there were others. `koloni`:
  a `.koloni` in it; `git`: a `.git`; `blocked`: a folder KOLONİ never opens as a project.
  Inside a place KOLONİ never opens nothing is listed (422).
- A project may not be the home folder, a drive's root or KOLONİ's own folder (422).
"""

import os
import sys
from pathlib import Path

import pytest

from app.config import REPO_ROOT

ORIGIN = "http://127.0.0.1:8790"
OWN = {"Origin": ORIGIN}


def browse(client, path=None, headers=OWN):
    return client.post("/api/folders/browse", json={} if path is None else {"path": str(path)},
                       headers=headers)


def test_browsing_lists_folders_only_with_what_each_one_is(client, tmp_path):
    root = tmp_path / "places"
    for name in ("alpha", "beta", ".hidden"):
        (root / name).mkdir(parents=True)
    (root / "alpha" / ".koloni").mkdir()
    (root / "beta" / ".git").mkdir()
    (root / "secret.txt").write_text("x", encoding="utf-8")
    answer = browse(client, root)
    assert answer.status_code == 200, answer.text
    found = answer.json()
    assert Path(found["path"]) == root.resolve() and found["more"] is False
    entries = {entry["name"]: entry for entry in found["entries"]}
    assert set(entries) == {"alpha", "beta", ".hidden"}  # no file's name
    assert (entries["alpha"]["koloni"], entries["alpha"]["git"]) == (True, False)
    assert (entries["beta"]["koloni"], entries["beta"]["git"]) == (False, True)
    assert entries[".hidden"]["hidden"] and not entries["alpha"]["hidden"]
    assert not any(entry["blocked"] for entry in entries.values())
    assert Path(entries["alpha"]["path"]) == (root / "alpha").resolve()
    assert found["parts"][-1]["name"] == "places"
    assert Path(found["parts"][-1]["path"]) == root.resolve()
    assert found["shortcuts"]


def test_a_place_kolonis_never_opens_is_shown_blocked_and_nothing_in_it_is_listed(
    client, tmp_path
):
    home = Path.home()  # the test's (conftest): its .ssh is a place KOLONİ never opens
    (home / ".ssh").mkdir(parents=True)
    (home / "Desktop").mkdir()
    entries = {e["name"]: e for e in browse(client, home).json()["entries"]}
    assert entries[".ssh"]["blocked"] and not entries["Desktop"]["blocked"]
    refused = browse(client, home / ".ssh")
    assert refused.status_code == 422, refused.text


def test_at_most_500_folders_are_listed_and_more_says_there_were_others(client, tmp_path):
    root = tmp_path / "many"
    for number in range(503):
        (root / f"f{number:03}").mkdir(parents=True)
    found = browse(client, root).json()
    assert len(found["entries"]) == 500 and found["more"] is True


def test_browsing_is_only_from_the_apps_own_page_and_only_posted(client, tmp_path):
    assert browse(client, tmp_path, headers={}).status_code == 403
    # A GET lists nothing: 405, or 404 where a built page (frontend/dist) takes every GET.
    got = client.get("/api/folders/browse")
    assert got.status_code in (404, 405) and "entries" not in got.text
    assert browse(client, tmp_path / "nope").status_code == 422


def test_the_home_folder_a_drives_root_or_kolonis_own_folder_is_no_project(client, tmp_path):
    home = Path.home()
    home.mkdir(parents=True, exist_ok=True)
    for refused in (home, Path(tmp_path.anchor), REPO_ROOT):
        answer = client.post("/api/projects", json={"root_path": str(refused)})
        assert answer.status_code == 422, (refused, answer.text)
    # B-73: a drive's root is said to be one, by its path as it is written
    said = client.post("/api/projects", json={"root_path": tmp_path.anchor}).json()["detail"]
    assert said == f"{tmp_path.anchor} cannot be opened as a folder: it is a drive's root"


def test_no_folder_inside_kolonis_own_is_a_project_but_its_e2e_project(
    client, tmp_path, monkeypatch
):
    from app.workspace import not_a_project

    # Its code, git's hooks, its record (the database): what agents there would change.
    for inside in (REPO_ROOT / "app", REPO_ROOT / ".git", REPO_ROOT / "runtime" / "data"):
        assert not_a_project(inside), inside
    answer = client.post("/api/projects", json={"root_path": str(REPO_ROOT / "app")})
    assert answer.status_code == 422, answer.text
    # The one exception: the folder KOLONİ's e2e works in (frontend/e2e/paths.mjs).
    e2e = REPO_ROOT / "runtime" / "e2e" / "project"
    assert not_a_project(e2e) is None and not_a_project(e2e / "deeper")
    if sys.platform == "win32":
        assert not_a_project(Path(str(e2e).upper())) is None  # (as Windows reads it: any case)
    # And the browser lists it and the folder it is in (its spec goes there), nothing else there.
    from app.api.folders import _in_a_never_place

    assert _in_a_never_place(e2e) is None and _in_a_never_place(e2e.parent) is None
    assert _in_a_never_place(e2e.parent / "data") and _in_a_never_place(e2e / "deeper")
    # A record of KOLONİ's somewhere else is no project either, nor a folder in it.
    record = tmp_path / "record"
    monkeypatch.setenv("KOLONI_RUNTIME_ROOT", str(record))
    (record / "project").mkdir(parents=True)
    for refused in (record, record / "project"):
        assert client.post("/api/projects", json={"root_path": str(refused)}).status_code == 422
    entries = {e["name"]: e for e in browse(client, tmp_path).json()["entries"]}
    assert entries["record"]["blocked"]


# Never one of these is looked at on disk: a share would be dialled (and NTLM sent).
FAR = ["\\\\server\\share", "//server/share", "/\\server\\share", "\\/server/share",
       "\\\\?\\UNC\\server\\share", "\\\\.\\C:\\", "\\\\?\\" + str(REPO_ROOT),
       "/\\?\\" + str(REPO_ROOT)]


@pytest.mark.parametrize("raw", FAR)
def test_a_network_or_device_path_is_neither_browsed_nor_opened(client, raw):
    refused = browse(client, raw)
    assert refused.status_code == 422 and "not a full path" in refused.json()["detail"]  # (first)
    assert client.post("/api/projects", json={"root_path": raw}).status_code == 422


def _link(target: Path, link: Path) -> None:
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def test_a_link_in_a_folder_is_not_followed_and_is_not_browsed(client, tmp_path):
    root = tmp_path / "places"
    (root / "real" / ".koloni").mkdir(parents=True)
    _link(root / "real", root / "door")
    entries = {e["name"]: e for e in browse(client, root).json()["entries"]}
    assert not entries["real"]["blocked"] and entries["real"]["koloni"]
    if sys.platform == "win32":  # (a junction says it is a folder's without being followed)
        assert entries["door"]["blocked"] and not entries["door"]["koloni"]
    else:
        assert "door" not in entries
    assert browse(client, root / "door").status_code == 422


def test_the_drives_are_listed_without_being_looked_at(client, tmp_path, monkeypatch):
    monkeypatch.setattr(os, "listdrives", lambda: ["Q:\\"], raising=False)
    assert {"name": "Q:\\", "path": "Q:\\"} in browse(client, tmp_path).json()["shortcuts"]
