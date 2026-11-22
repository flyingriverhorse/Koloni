"""Kanıtlı bitiş S6 (plan decision 10): the tests related to a turn's changed files, read from the
test command's own words - run first at the turn's end, the whole suite after it in the background.
Model-free: `proof_related.related` on folders made here."""

import json

import pytest

from app import proof
from app.proof_related import related


def made(root, *files):
    for rel in files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x\n", encoding="utf-8")


def narrowed(root, command, paths, cwd=".", yours=True):
    found = related(proof.TestRun(command, cwd, yours), list(paths), root)
    return found and found.command


@pytest.mark.parametrize("command", [
    "pytest", "python -m pytest -q", ".venv/Scripts/python.exe -m pytest", "uv run pytest",
    "poetry run pytest -x", ".venv/bin/pytest"])
def test_pytest_is_read_first_or_after_a_known_launcher(tmp_path, command):
    made(tmp_path, "tests/test_greet.py")
    assert narrowed(tmp_path, command, ["tests/test_greet.py"]) == f"{command} tests/test_greet.py"


@pytest.mark.parametrize(("config", "body"), [
    ("pytest.ini", "[pytest]\naddopts = -q --ignore=live\n"),
    ("pytest.ini", "[pytest]\nnorecursedirs = manual\n"),
    ("pyproject.toml", '[tool.pytest.ini_options]\naddopts = ["--deselect", "tests/x.py::t"]\n'),
    ("setup.cfg", "[tool:pytest]\naddopts = --ignore-glob=*live*\n"),
    ("tox.ini", "[pytest]\nnorecursedirs = .git manual\n"),
    ("conftest.py", "collect_ignore = ['tests/test_skipme.py']\n"),
    ("tests/conftest.py", "def pytest_ignore_collect(collection_path):\n    return None\n"),
    ("pytest.ini", "[pytest\nbroken"),  # (one it cannot read: nothing narrower)
])
def test_pytest_exclusions_in_the_projects_config_leave_no_related_step(tmp_path, config, body):
    # (Fail closed: a file named on the command line bypasses them - B3 of the review.)
    made(tmp_path, "tests/test_greet.py")
    (tmp_path / config).write_text(body, encoding="utf-8")
    assert narrowed(tmp_path, "pytest", ["tests/test_greet.py"]) is None


def test_pytest_testpaths_keep_the_candidates_under_them(tmp_path):
    made(tmp_path, "app/mod.py", "tests/test_mod.py", "other/deep/test_mod.py")
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -q\ntestpaths = tests\n",
                                         encoding="utf-8")
    assert narrowed(tmp_path, "pytest", ["app/mod.py"]) == "pytest tests/test_mod.py"
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests/u*\n", encoding="utf-8")
    assert narrowed(tmp_path, "pytest", ["app/mod.py"]) is None  # (a glob: not read)


def test_a_pyproject_without_pytest_leaves_the_ini_beside_it_read(tmp_path):
    made(tmp_path, "tests/test_greet.py")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    (tmp_path / "tox.ini").write_text("[pytest]\naddopts = --ignore=live\n", encoding="utf-8")
    assert narrowed(tmp_path, "pytest", ["tests/test_greet.py"]) is None


@pytest.mark.parametrize("name", ["tests/test_ı.py", "tests/test_x².py", "tests/../../x/test_a.py",
                                  "tests/.hidden/test_a.py"])
def test_only_plain_ascii_names_with_no_parent_part_go_on_a_command_line(tmp_path, name):
    made(tmp_path, name)
    assert narrowed(tmp_path, "pytest", [name]) is None


def test_pytest_runs_the_changed_test_files_and_those_named_for_a_changed_module(tmp_path):
    made(tmp_path, "app/greet.py", "tests/test_greet.py", "tests/test_other.py",
         "tests/test_new.py", "node_modules/x/test_greet.py", ".venv/test_greet.py")
    assert narrowed(tmp_path, "python -m pytest -q", ["app/greet.py", "tests/test_new.py"]) == (
        "python -m pytest -q tests/test_greet.py tests/test_new.py")
    # (a module_test.py beside it counts too; a change no test is named for gives none)
    made(tmp_path, "app/greet_test.py")
    assert narrowed(tmp_path, "pytest", ["app/greet.py"]) == (
        "pytest app/greet_test.py tests/test_greet.py")
    assert narrowed(tmp_path, "pytest -q", ["app/nothing_names_me.py"]) is None


@pytest.mark.parametrize("command", [
    "python -m pytest -q tests/",  # (it names its own tests: narrower is not known)
    "pytest -k 'a and b'",
    "pytest -q && npm test",  # (more than one command)
    "python check.py",  # (no runner KOLONİ reads)
    # (a runner named by another tool - its environment, target or session - is not the runner)
    "tox -e pytest", "make pytest", "nox -s pytest", "just pytest", "cmd /c pytest",
    "PYTHONPATH=. pytest",
    # (what the user left out stays out: a file on the command line would bypass it)
    "pytest --ignore=tests/live", "pytest --ignore tests/live", "pytest --ignore-glob=*live*",
    "pytest --deselect tests/test_greet.py::test_slow",
    # (a config it picks or overrides is not the one read here: review round 2)
    "pytest -c ci.ini", "pytest -cci.ini", "pytest --config-file=ci.ini",
    "pytest -o addopts=--ignore=live", "pytest --override-ini=norecursedirs=live",
    "pytest --rootdir=sub", "pytest -p no:cacheprovider",
])
def test_a_command_it_cannot_read_gives_none(tmp_path, command):
    made(tmp_path, "tests/test_greet.py")
    assert narrowed(tmp_path, command, ["tests/test_greet.py"]) is None


def test_pytest_keeps_its_options_with_their_values(tmp_path):
    made(tmp_path, "tests/test_greet.py")
    assert narrowed(tmp_path, "pytest -n 4 -m unit -q", ["tests/test_greet.py"]) == (
        "pytest -n 4 -m unit -q tests/test_greet.py")


def test_pytest_addopts_in_the_environment_leaves_no_related_step(tmp_path, monkeypatch):
    # (KOLONİ's runs get its environment: what PYTEST_ADDOPTS leaves out a named file bypasses.)
    made(tmp_path, "tests/test_greet.py")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--ignore=tests/live")
    assert narrowed(tmp_path, "pytest", ["tests/test_greet.py"]) is None


@pytest.mark.parametrize("name", ["build/test_gen.py", "dist/test_x.py", "pkg.egg/test_x.py",
                                  "CVS/test_x.py", "_darcs/test_x.py", "venv/test_x.py"])
def test_a_test_file_under_pytests_default_norecursedirs_is_not_named(tmp_path, name):
    made(tmp_path, name)
    assert narrowed(tmp_path, "pytest", [name]) is None


@pytest.mark.parametrize("paths", [
    ["conftest.py"],  # (what every test reads)
    ["pyproject.toml", "tests/test_greet.py"],  # (a config file: the whole suite only)
    ["web/a.ts", "tests/test_greet.py"],  # (another language's file)
])
def test_a_change_it_cannot_place_gives_none(tmp_path, paths):
    made(tmp_path, "tests/test_greet.py", "conftest.py")
    assert narrowed(tmp_path, "pytest -q", paths) is None


def test_documents_beside_the_code_are_left_aside(tmp_path):
    made(tmp_path, "tests/test_greet.py")
    assert narrowed(tmp_path, "pytest", ["README.md", "tests/test_greet.py"]) == (
        "pytest tests/test_greet.py")


def test_a_deleted_test_file_is_not_named_and_an_odd_name_gives_none(tmp_path):
    made(tmp_path, "tests/test_greet.py", "tests/test_it now.py")
    assert narrowed(tmp_path, "pytest", ["tests/test_gone.py", "tests/test_greet.py"]) == (
        "pytest tests/test_greet.py")
    # (a name a shell would read otherwise is the agent's word: not put on a command line)
    assert narrowed(tmp_path, "pytest", ["tests/test_it now.py"]) is None


def test_a_part_reads_its_own_files_only_from_its_folder(tmp_path):
    made(tmp_path, "api/tests/test_greet.py", "tests/test_greet.py")
    assert narrowed(tmp_path, "pytest", ["api/tests/test_greet.py", "tests/test_greet.py"],
                    cwd="api") == "pytest tests/test_greet.py"
    assert narrowed(tmp_path, "pytest", ["tests/test_greet.py"], cwd="api") is None


def test_too_many_files_give_none(tmp_path):
    files = [f"tests/test_{n}.py" for n in range(41)]
    made(tmp_path, *files)
    assert narrowed(tmp_path, "pytest", files) is None


def test_vitest_and_jest_name_the_changed_sources(tmp_path):
    made(tmp_path, "src/a.ts", "src/b.tsx")
    assert narrowed(tmp_path, "npx vitest run", ["src/a.ts", "src/b.tsx"]) == (
        "npx vitest related --run --passWithNoTests src/a.ts src/b.tsx")
    assert narrowed(tmp_path, "npx vitest run --config web.config.ts", ["src/a.ts"]) == (
        "npx vitest related --config web.config.ts --run --passWithNoTests src/a.ts")
    assert narrowed(tmp_path, "npx jest --ci", ["src/a.ts"]) == (
        "npx jest --ci --passWithNoTests --findRelatedTests src/a.ts")
    assert narrowed(tmp_path, "npx vitest run", ["src/a.css"]) is None
    assert narrowed(tmp_path, "npx jest --watch", ["src/a.ts"]) is None


@pytest.mark.parametrize(("script", "said"), [
    ("vitest run", "npx --no vitest related --run --passWithNoTests src/a.ts"),
    ("vitest", "npx --no vitest related --run --passWithNoTests src/a.ts"),
    ("jest", "npm test -- --passWithNoTests --findRelatedTests src/a.ts"),
    ("jest && eslint .", None),
    ("node t.js", None),
])
def test_npm_test_reads_its_script(tmp_path, script, said):
    made(tmp_path, "src/a.ts", "node_modules/.bin/vitest")
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": script}}),
                                           encoding="utf-8")
    assert narrowed(tmp_path, "npm test", ["src/a.ts"]) == said


def test_npm_test_runs_vitest_through_npx_only_where_the_projects_own_is_installed(tmp_path):
    # (npx would fetch one that is not: never the project's own command then)
    made(tmp_path, "web/src/a.ts")
    (tmp_path / "web" / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}),
                                                   encoding="utf-8")
    made(tmp_path, "node_modules/.bin/vitest-ui")  # (not vitest itself)
    assert narrowed(tmp_path, "npm test", ["web/src/a.ts"], cwd="web") is None
    made(tmp_path, "node_modules/.bin/vitest.cmd")  # (a workspace's root holds it: found above)
    assert narrowed(tmp_path, "npm test", ["web/src/a.ts"], cwd="web") == (
        "npx --no vitest related --run --passWithNoTests src/a.ts")


def test_npm_test_with_a_pretest_script_has_no_vitest_related_step(tmp_path):
    # (npm test runs `pretest` first - a build, a codegen - and npx vitest would not)
    made(tmp_path, "src/a.ts", "node_modules/.bin/vitest")
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {
        "test": "vitest", "pretest": "node gen.js"}}), encoding="utf-8")
    assert narrowed(tmp_path, "npm test", ["src/a.ts"]) is None


@pytest.mark.parametrize(("config", "body"), [
    ("package.json", json.dumps({"scripts": {"test": "jest"},
                                 "jest": {"testPathIgnorePatterns": ["/live/"]}})),
    ("jest.config.js", "module.exports = { testPathIgnorePatterns: ['/live/'] }\n"),
])
def test_jest_with_ignored_test_paths_has_no_related_step(tmp_path, config, body):
    # (shortcut in the code: jest is not measured here - fail closed; vitest's `related` keeps
    # the config's `exclude`, measured)
    made(tmp_path, "src/a.ts")
    (tmp_path / config).write_text(body, encoding="utf-8")
    assert narrowed(tmp_path, "npx jest", ["src/a.ts"]) is None
    if config == "package.json":
        assert narrowed(tmp_path, "npm test", ["src/a.ts"]) is None


def test_go_tests_the_changed_packages(tmp_path):
    made(tmp_path, "greet/greet.go", "greet/greet_test.go", "store/db.go", "main.go")
    assert narrowed(tmp_path, "go test ./...", ["greet/greet.go", "main.go"]) == (
        "go test . ./greet")
    assert narrowed(tmp_path, "go test -race ./...", ["store/db.go"]) == "go test -race ./store"
    assert narrowed(tmp_path, "go test ./...", ["go.mod"]) is None
    assert narrowed(tmp_path, "go test -run X ./...", ["store/db.go"]) is None


def test_cargo_tests_the_changed_crates_of_a_workspace(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[workspace]\nmembers = ["a", "b"]\n', encoding="utf-8")
    for name in ("a", "b"):
        made(tmp_path, f"{name}/src/lib.rs")
        (tmp_path / name / "Cargo.toml").write_text(f'[package]\nname = "{name}-crate"\n',
                                                    encoding="utf-8")
    assert narrowed(tmp_path, "cargo test", ["b/src/lib.rs"]) == "cargo test -p b-crate"
    assert narrowed(tmp_path, "cargo test --workspace", ["b/src/lib.rs"]) is None


def test_cargo_of_one_crate_has_nothing_narrower(tmp_path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "one"\n', encoding="utf-8")
    made(tmp_path, "src/lib.rs")
    assert narrowed(tmp_path, "cargo test", ["src/lib.rs"]) is None


def test_dotnet_tests_the_one_test_project_of_the_change(tmp_path):
    made(tmp_path, "Greet/Greeter.cs", "Greet.Tests/GreeterTests.cs")
    (tmp_path / "Greet" / "Greet.csproj").write_text("<Project></Project>", encoding="utf-8")
    (tmp_path / "Greet.Tests" / "Greet.Tests.csproj").write_text(
        '<Project><ItemGroup><PackageReference Include="Microsoft.NET.Test.Sdk" />'
        '<ProjectReference Include="..\\Greet\\Greet.csproj" /></ItemGroup></Project>',
        encoding="utf-8")
    assert narrowed(tmp_path, "dotnet test", ["Greet/Greeter.cs"]) == (
        "dotnet test Greet.Tests/Greet.Tests.csproj")
    assert narrowed(tmp_path, "dotnet test", ["Greet.Tests/GreeterTests.cs"]) == (
        "dotnet test Greet.Tests/Greet.Tests.csproj")
    assert narrowed(tmp_path, "dotnet test App.sln", ["Greet/Greeter.cs"]) is None


def test_the_narrower_run_keeps_whose_command_it_is(tmp_path):
    made(tmp_path, "tests/test_greet.py")
    found = related(proof.TestRun("pytest", ".", False), ["tests/test_greet.py"], tmp_path)
    assert found == proof.TestRun("pytest tests/test_greet.py", ".", False)


def test_a_related_row_says_so():
    assert proof.related_said("Tests passed: pytest a.py - 3 passed") == (
        "Related tests passed: pytest a.py - 3 passed")
    assert proof.related_said("No test command") == "No test command"
