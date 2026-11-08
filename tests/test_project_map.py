"""K-buyuk-proje, first slice: the project map - the parts of a project found by their marker
files, each with its language, file count, AGENTS.md and a guessed test command; what a copy of a
big project leaves out; the user's test commands; and the map in the Lead's brief."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from app import copies, project_map
from tests.test_chat_flow import text

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
OWN = {"Origin": "http://127.0.0.1:8790"}
PYTHON = Path("Scripts", "python.exe") if os.name == "nt" else Path("bin", "python")


def _put(root: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")
    return root


def monorepo(root: Path) -> Path:
    """A Python library with tests and the repository's .venv at the root, a TypeScript app with a
    test script, a site whose package.json has npm's no-test script, and loose files."""
    return _put(root, {
        f".venv/{PYTHON.as_posix()}": "", "README.md": "hi",
        "core/pyproject.toml": "[project]\nname = 'core'\n", "core/tests/test_a.py": "",
        "core/core/a.py": "", "core/AGENTS.md": "rules",
        "web/package.json": json.dumps({"scripts": {"test": "vitest run"}}),
        "web/tsconfig.json": "{}", "web/src/main.ts": "",
        "site/package.json": json.dumps(
            {"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}),
        "site/index.js": "",
    })


def _git(folder: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=folder, check=True, capture_output=True)


def test_a_monorepos_parts_with_their_languages_counts_and_test_guesses(tmp_path):
    found = project_map.scan(str(monorepo(tmp_path / "repo")))
    assert found["parts"] == [
        {"path": "core/", "language": "Python", "files": 4, "more": False, "agents_md": True,
         "guess": f"{Path('..', '.venv', PYTHON)} -m pytest"},
        {"path": "site/", "language": "JavaScript", "files": 2, "more": False,
         "agents_md": False, "guess": None},
        {"path": "web/", "language": "TypeScript", "files": 3, "more": False,
         "agents_md": False, "guess": "npm test"},
    ]
    assert (found["git"], found["big"], found["partial"], found["not_copied"]) == (
        False, False, False, [])


def test_a_part_uses_its_own_venv_and_pytest_said_in_its_config(tmp_path):
    root = _put(tmp_path / "repo", {
        f".venv/{PYTHON.as_posix()}": "", f"lib/.venv/{PYTHON.as_posix()}": "",
        "lib/setup.py": "", "lib/setup.cfg": "[tool:pytest]\n", "other/requirements.txt": "",
    })
    parts = {part["path"]: part["guess"] for part in project_map.scan(str(root))["parts"]}
    assert parts == {"lib/": f"{Path('.venv', PYTHON)} -m pytest", "other/": None}


def test_a_single_project_is_one_part_at_its_root_and_no_brief(tmp_path):
    root = _put(tmp_path / "one", {"pyproject.toml": "[project]\n", "src/x.py": "",
                                   "Cargo.toml": "", "go.mod": ""})
    found = project_map.edited(project_map.scan(str(root)), {})
    assert [(p["path"], p["language"], p["guess"]) for p in found["parts"]] == [
        ("./", "Python, Rust, Go", "cargo test")]
    assert project_map.brief(found) is None
    assert project_map.brief(project_map.edited(project_map.scan(str(tmp_path / "one" / "src")),
                                                {})) is None  # (no part at all)


def test_the_brief_holds_the_map_quoted_and_capped(tmp_path, monkeypatch):
    root = monorepo(tmp_path / "repo")
    found = project_map.edited(project_map.scan(str(root)), {"site/": 'npm run "x"'})
    told = project_map.brief(found)
    assert told is not None and told.startswith("The project's parts")
    assert '- "core/": Python, 4 files, test: "' in told and "has AGENTS.md" in told
    assert '- "site/": JavaScript, 2 files, test: "npm run \\"x\\"", no AGENTS.md' in told
    assert '- "web/": TypeScript, 3 files, test: "npm test", no AGENTS.md' in told
    no_test = project_map.brief(project_map.edited(project_map.scan(str(root)), {"web/": ""}))
    assert no_test is not None and '- "web/": TypeScript, 3 files, test: none, no' in no_test
    # One part that is not the project's own folder is a map too.
    alone = {**found, "parts": found["parts"][:1]}
    assert project_map.brief(alone) is not None
    monkeypatch.setattr(project_map, "MOST_BRIEF", 300)
    capped = project_map.brief(found)
    assert capped is not None and len(capped) < 340 and capped.endswith("more lines")


@needs_git
def test_what_git_ignores_is_not_walked_and_is_not_copied_only_when_too_big(tmp_path,
                                                                           monkeypatch):
    root = _put(tmp_path / "repo", {
        ".gitignore": "data/\nmlruns\n", "app/pyproject.toml": "", "app/a.py": "",
        "data/pyproject.toml": "", "data/big.csv": "", "mlruns/0/meta.yaml": "",
        "tools/package.json": "{}",
    })
    _git(root, "init", "-q")
    small = project_map.scan(str(root))
    assert [part["path"] for part in small["parts"]] == ["app/", "tools/"]
    assert (small["git"], small["big"], small["not_copied"]) == (True, False, [])
    monkeypatch.setattr(copies, "MAX_FILES", 3)
    big = project_map.scan(str(root), fresh=True)
    assert (big["big"], big["not_copied"]) == (True, ["data/", "mlruns/"])


@needs_git
def test_a_project_in_a_folder_its_repository_ignores_still_has_its_parts(tmp_path):
    repo = _put(tmp_path / "repo", {".gitignore": "runtime/\n"})
    _git(repo, "init", "-q")
    root = _put(repo / "runtime" / "proj", {"a/package.json": "{}", "b/go.mod": ""})
    found = project_map.scan(str(root))
    assert [p["path"] for p in found["parts"]] == ["a/", "b/"] and found["git"] is False


def test_the_caps_stop_the_count_and_the_walk(tmp_path, monkeypatch):
    root = _put(tmp_path / "repo", {"a/package.json": "{}", "b/package.json": "{}",
                                    **{f"a/f{n}.js": "" for n in range(8)}})
    monkeypatch.setattr(project_map, "MOST_COUNTED", 5)
    part = project_map.scan(str(root))["parts"][0]
    assert (part["path"], part["files"], part["more"]) == ("a/", 5, True)
    monkeypatch.setattr(project_map, "MOST_FOLDERS", 2)
    walked = project_map.scan(str(root), fresh=True)
    assert walked["partial"] and [p["path"] for p in walked["parts"]] == ["a/"]


def _link(target: Path, link: Path) -> None:
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def test_a_link_out_of_the_project_is_not_followed(tmp_path):
    outside = _put(tmp_path / "outside", {"pyproject.toml": "", "tests/t.py": "",
                                          **{f"f{n}.py": "" for n in range(5)}})
    root = _put(tmp_path / "repo", {"app/package.json": "{}"})
    _link(outside, root / "app" / "out")
    _link(outside, root / "elsewhere")
    found = project_map.scan(str(root))
    assert [(p["path"], p["files"]) for p in found["parts"]] == [("app/", 1)]


def test_a_secret_file_is_never_read(tmp_path, monkeypatch):
    root = _put(tmp_path / "repo", {
        "app/pyproject.toml": "[tool.pytest]", "app/.env": "TOKEN=pytest",
        "keys/.ssh/pyproject.toml": "pytest", "web/package.json": "{}",
        "web/secrets.json": "{}"})
    read: list[str] = []
    real = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path: read.append(path.name) or real(path))
    found = project_map.scan(str(root))
    assert [p["path"] for p in found["parts"]] == ["app/", "web/"]  # (not in .ssh/)
    assert ".env" not in read and "secrets.json" not in read and read.count("pyproject.toml") == 1


def test_a_changed_marker_makes_the_map_again_and_else_it_is_kept(tmp_path):
    root = _put(tmp_path / "repo", {"web/package.json": "{}", "api/go.mod": ""})
    first = project_map.scan(str(root))
    assert project_map.scan(str(root)) is first
    (root / "web" / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
    os.utime(root / "web" / "package.json", ns=(1, 1))  # (a new mtime, however fast the disk)
    second = project_map.scan(str(root))
    assert second is not first and second["parts"][1]["guess"] == "npm test"
    _put(root, {"cli/Cargo.toml": ""})
    assert [p["path"] for p in project_map.scan(str(root))["parts"]] == ["api/", "cli/", "web/"]




def test_a_map_a_cap_cut_short_is_kept_until_refresh(tmp_path, monkeypatch):
    root = _put(tmp_path / "repo", {"a/package.json": "{}", "b/go.mod": ""})
    monkeypatch.setattr(project_map, "MOST_SECONDS", -1.0)  # (the full walk's time is up at once)
    made = []
    real = project_map._scan
    monkeypatch.setattr(project_map, "_scan", lambda at: made.append(at) or real(at))
    first = project_map.scan(str(root))
    assert first["partial"] and project_map.scan(str(root)) is first
    assert project_map.scan(str(root)) is first and len(made) == 1
    project_map.scan(str(root), fresh=True)
    assert len(made) == 2


def test_the_users_test_command_is_saved_from_the_page_only_and_survives_a_refresh(client,
                                                                                tmp_path):
    root = monorepo(tmp_path / "repo")
    pid = client.post("/api/projects", json={"root_path": str(root)}).json()["id"]
    url = f"/api/projects/{pid}/map/test"
    shown = client.get(f"/api/projects/{pid}/map")
    assert shown.status_code == 200, shown.text
    assert [p["test"] for p in shown.json()["parts"]][1:] == [None, "npm test"]
    put = {"path": "site/", "command": "  npm run check  "}
    assert client.put(url, json=put).status_code == 403
    assert client.put(url, json={"path": "nope/", "command": "x"}, headers=OWN).status_code == 422
    for bad in ("npm test\nrm -rf x", "a\x00", "x" * 501):
        assert client.put(url, json={"path": "site/", "command": bad},
                          headers=OWN).status_code == 422
    saved = client.put(url, json=put, headers=OWN).json()
    site = saved["parts"][1]
    assert (site["test"], site["guess"], site["edited"]) == ("npm run check", None, True)
    again = client.post(f"/api/projects/{pid}/map/refresh").json()["parts"][1]
    assert (again["test"], again["edited"]) == ("npm run check", True)
    # Empty: no test, over the guess. Reset: the guess again.
    web = client.put(url, json={"path": "web/", "command": ""}, headers=OWN).json()["parts"][2]
    assert (web["test"], web["guess"], web["edited"]) == (None, "npm test", True)
    assert client.delete(url, params={"path": "web/"}).status_code == 403
    web = client.delete(url, params={"path": "web/"}, headers=OWN).json()["parts"][2]
    assert (web["test"], web["edited"]) == ("npm test", False)
    # A part gone from the map keeps what the user set: it can still be changed and reset.
    shutil.rmtree(root / "site")
    assert client.post(f"/api/projects/{pid}/map/refresh").json()["parts"][1]["path"] == "web/"
    assert client.put(url, json={"path": "site/", "command": ""}, headers=OWN).status_code == 200
    assert client.delete(url, params={"path": "site/"}, headers=OWN).status_code == 200
    assert (root / ".koloni").exists() is False  # (nothing written into the user's folder)


def _lead_system(make_client, wait_run, root: Path) -> str:
    from tests.test_spawn import begin

    client, model = make_client([text("ok")])
    cid, rid = begin(client, root)
    wait_run(client, cid, rid)
    return model.calls[0][0]["content"]


@pytest.fixture
def map_ready(monkeypatch):
    """The Lead's first step comes once the map is made: a turn by itself does not wait."""
    from app.agent import AgentRunner

    real = AgentRunner._hold_room

    async def held(self, lead):
        if (making := self._map_tasks.get(lead.run_id)) is not None:
            await asyncio.wait({making})
        await real(self, lead)

    monkeypatch.setattr(AgentRunner, "_hold_room", held)


def test_the_lead_is_told_the_map_only_when_the_project_has_more_than_one_part(
        make_client, wait_run, tmp_path, map_ready):
    told = _lead_system(make_client, wait_run, monorepo(tmp_path / "repo"))
    assert "The project's parts" in told and '- "web/": TypeScript' in told
    one = _put(tmp_path / "one", {"pyproject.toml": "", "tests/t.py": ""})
    assert "The project's parts" not in _lead_system(make_client, wait_run, one)


def test_a_lead_that_skips_folder_for_a_task_naming_a_part_is_told_so(
        make_client, wait_run, tmp_path, map_ready):
    # K-lead-folder (R115): the agent still opens as asked - the Lead chooses the part.
    from tests.test_claim_scenarios import calls
    from tests.test_spawn import begin, call, step

    def told(root, task, **more):
        client, _model = make_client({
            "Lead": [step(call("spawn_agent", {"role": "Coder", "task": task, **more}, "s")),
                     text("done")],
            "Coder": [text("did it")]})
        cid, rid = begin(client, root, mode="full_auto", spawn_approval="never")
        ((_status, result),) = calls(wait_run(client, cid, rid), "Lead", "spawn_agent")
        return result

    repo = monorepo(tmp_path / "repo")
    assert 'The task names the part "core/": pass it as folder next time' in told(
        repo, "fix core's tests")
    assert "pass it as folder" not in told(repo, "fix core's tests", folder="core")
    one = _put(tmp_path / "one", {"pyproject.toml": "", "core/t.py": ""})
    assert "pass it as folder" not in told(one, "fix core's tests")
    found = project_map.scan(str(repo))
    assert project_map.named(found, "see web/src/main.ts") == "web/"
    assert project_map.named(found, "sync core and web") is None  # (several: none)
    assert project_map.named(found, "the score-core") is None  # (a word's piece: none)
    assert project_map.named(found, "Run the tests in core.") == "core/"
    assert project_map.named(found, "fix ./core/tests") == "core/"
    assert project_map.named(found, "see packages/core/x") is None  # (another folder's)
    assert project_map.named(found, "fix core", part="core/") is None  # (the opener's own)


def test_a_turn_does_not_wait_for_its_map(make_client, wait_run, tmp_path, monkeypatch):
    slow = threading.Event()
    monkeypatch.setattr(project_map, "scan", lambda *_args: slow.wait(10) and {})
    try:
        told = _lead_system(make_client, wait_run, monorepo(tmp_path / "repo"))
    finally:
        slow.set()
    assert "The project's parts" not in told


def test_the_projects_documents_are_listed_with_their_first_heading(tmp_path):
    root = _put(tmp_path / "repo", {
        "README.md": "\n# Hello  world\nmore", "notes.txt": "x", "docs/a.md": "No heading here\n",
        "docs/b/c.md": "intro\n# C " + "y" * 100, "docs/.env.md": "# KEY=1",
        "docs/node_modules/x.md": "# no", ".koloni/rules.md": "# no",
    })
    said = project_map.documents(str(root))
    assert said.splitlines() == [
        project_map.DOCS_HEAD, '- "README.md" — "Hello world"', '- "docs/a.md" — "No heading here"',
        f'- "docs/b/c.md" — "C {"y" * 78}…"']
    assert project_map.documents(str(_put(tmp_path / "none", {"a.py": ""}))) == ""


def test_the_lead_is_told_the_documents(make_client, wait_run, tmp_path):
    root = _put(tmp_path / "repo", {"pyproject.toml": "", "docs/guide.md": "# The guide"})
    assert f'{project_map.DOCS_HEAD}\n- "docs/guide.md" — "The guide"' in _lead_system(
        make_client, wait_run, root)
