"""Full auto's judge reads the program a command runs where an agent wrote it (`planted_program`):
the script an interpreter or a shell is handed, or the program named by its path - one an agent's
write on record still stands as, in the project."""

import sys
from pathlib import Path

import pytest

from app.agent.risk_judge_mixin import _named_file, _no_local_code, planted_program
from app.db.models import Agent, Conversation, FileChange, Project
from app.db.models import Run as RunRow
from app.db.session import make_engine, make_session_factory
from app.workspace import sha256_text
from tests.conftest import migrated_copy

WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="Windows paths")


@pytest.fixture
def project(tmp_path):
    """(factory, root, wrote): a project whose agent's writes `wrote(rel, text)` puts on record and
    in its folder."""
    root = tmp_path / "proj"
    root.mkdir()
    migrated_copy(tmp_path / "k.db")
    factory = make_session_factory(make_engine(tmp_path / "k.db"))
    with factory() as session:
        session.add(Project(id="p", name="p", root_path=str(root)))
        session.flush()
        session.add(Conversation(id="c", project_id="p"))
        session.flush()
        session.add(RunRow(id="r", conversation_id="c", status="completed"))
        session.flush()
        session.add(Agent(id="a", run_id="r", role_name="Lead", tools=[]))
        session.commit()

    def wrote(rel: str, text: str = "print(1)\n") -> Path:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        with factory() as session:
            session.add(
                FileChange(
                    run_id="r",
                    agent_id="a",
                    path=rel,
                    kind="create",
                    after_content=text,
                    after_sha=sha256_text(text),
                    status="applied",
                )
            )
            session.commit()
        return path.resolve()

    return factory, root, wrote


@pytest.mark.parametrize(
    "line, rel",
    [
        ("node gen.js", "gen.js"),
        ("python gen.py --out x", "gen.py"),
        ("python -u -X utf8 gen.py", "gen.py"),
        ("./run.sh", "run.sh"),
        ("bash run.sh", "run.sh"),
        ("powershell -ExecutionPolicy Bypass -File run.ps1", "run.ps1"),
        pytest.param(".\\run.cmd", "run.cmd", marks=WINDOWS),  # (a backslash is Windows' alone)
        ("& ./run.ps1", "run.ps1"),
        ('node "my tools/gen.js"', "my tools/gen.js"),
        # (review H1: as the runner finds it - a module, a folder, a name with no ending)
        ("python -m gen", "gen.py"),
        ("python -u -m tools.gen", "tools/gen.py"),
        ("python -m pkg", "pkg/__main__.py"),
        ("python pkg", "pkg/__main__.py"),
        ("node gen", "gen.js"),
        ("node lib", "lib/index.js"),
        ("./run", "run.ps1"),
        # (review H2: a shell's -e, -r, -p, -m are no code of the line's)
        ("bash -e run.sh", "run.sh"),
        ("zsh -e run.sh", "run.sh"),
        ("bash -r run.sh", "run.sh"),
        ("powershell -mta -File run.ps1", "run.ps1"),
        # (a shell's -c code by its first word, where that is a file of the folder's)
        ("bash -c ./run.sh", "run.sh"),
        ("powershell -c ./run.ps1", "run.ps1"),
        # (what make, docker and Node's runners read for what they run)
        ("make all", "Makefile"),
        ("make -f build.mk all", "build.mk"),
        ("docker build -t x .", "Dockerfile"),
        ("docker build -f ci/Dockerfile .", "ci/Dockerfile"),
        ("npm run build", "package.json"),
    ],
)
def test_the_script_an_agent_wrote(project, line, rel):
    factory, root, wrote = project
    path = wrote(rel)
    assert planted_program(factory, "c", root, line, ".") == path


def test_in_a_folder_below_with_options_before_the_script(project):
    factory, root, wrote = project
    path = wrote("sub/tools/x.py")
    assert planted_program(factory, "c", root, "python -u tools/x.py", "sub") == path


@pytest.mark.parametrize(
    "line", ['python -c "print(1)"', 'node -e "1"', "bash -c 'x'", "pytest -q", "gen"]
)
def test_no_file_where_the_line_holds_its_code_or_runs_none_of_its_own(project, line):
    factory, root, wrote = project
    wrote("gen.py")
    wrote("gen.js")
    assert planted_program(factory, "c", root, line, ".") is None


def test_the_users_own_file_and_one_they_changed_since_are_not_the_agents(project):
    factory, root, wrote = project
    (root / "mine.py").write_text("print('mine')\n", encoding="utf-8")
    assert planted_program(factory, "c", root, "python mine.py", ".") is None
    wrote("gen.py").write_text("print('changed by the user')\n", encoding="utf-8")
    assert planted_program(factory, "c", root, "python gen.py", ".") is None


def test_never_a_file_out_of_the_project(project, tmp_path):
    factory, root, wrote = project
    wrote("../x.js")
    assert (tmp_path / "x.js").is_file()
    assert planted_program(factory, "c", root, "node ../x.js", ".") is None
    assert planted_program(factory, "c", root, f"node {tmp_path / 'x.js'}", ".") is None


@pytest.mark.parametrize(
    "line, rel, exact",
    [
        ("python -X dev x.py", "x.py", True),
        ("python -m x", "x.py", True),
        ("node app.js", "app.js", True),
        ("bash -e run.sh", "run.sh", True),
        ("make all", "Makefile", True),
        ("docker build -t img .", "Dockerfile", True),
        ("npm run build", "package.json", True),
        # (shown, never all it runs: an option that loads more, a shell's code around it)
        ("node --require ./evil.js app.js", "app.js", False),
        ("ruby -Ilib x.rb", "x.rb", False),
        ("bash --norc run.sh", "run.sh", False),
        ("bash -lc ./run.sh", "run.sh", False),
        ("/bin/bash -lc './run.sh'", "run.sh", False),
        ('powershell -Command "& ./x.ps1"', "x.ps1", False),
        ("cmd /c ./run.sh", "run.sh", False),
        ("pwsh -NoProfile -ExecutionPolicy Bypass -File x.ps1", "x.ps1", True),
        # (round 3: a package's __init__.py runs first; bun and R load the folder's settings;
        # PowerShell's -SettingsFile and -PSConsoleFile, whose values are no script)
        ("python -m pkg", "pkg/__main__.py", False),
        ("python pkg", "pkg/__main__.py", False),
        ("bun app.js", "app.js", False),
        ("Rscript x.R", "x.R", False),
        ("pwsh -SettingsFile s.json -File x.ps1", "x.ps1", False),
        ("pwsh -PSConsoleFile c.psc1 -File x.ps1", "x.ps1", False),
    ],
)
def test_the_file_found_and_whether_it_is_all_a_line_runs(project, line, rel, exact):
    _factory, root, _wrote = project
    (root / "pkg").mkdir()
    for name in ("x.py", "app.js", "run.sh", "Makefile", "Dockerfile", "package.json", "x.R"):
        (root / name).write_text("x\n", encoding="utf-8")
    for name in ("x.rb", "x.ps1", "pkg/__main__.py", "pkg/__init__.py", "s.json", "c.psc1"):
        (root / name).write_text("x\n", encoding="utf-8")
    assert _named_file(root, line, ".") == ((root / rel).resolve(), exact)


@pytest.mark.parametrize(
    "line",
    [
        # (review round 2: the forms whose file is not the one they run, or not plain - none)
        "make -C sub all",
        "make -Csub",
        "npm --prefix sub run x",
        "npm run x -w sub",
        "npx tsx x.ts",
        "npm exec -- tsx x.ts",
        "pnpm exec node x.js",
        "yarn node x.js",
        "pnpm -C sub run x",
        "yarn --cwd sub x",
        "docker compose --project-directory sub up",
        "docker compose up",
        "docker build sub --no-cache",
        "docker buildx build sub",
        "powershell -EncodedCommand ZQBjAGgAbwA=",
        "bash -c 'python x.py'",
        # (round 3: a variable set on make's line runs what it names)
        "make SHELL=./evil.sh",
        "make CC=./evil.sh all",
    ],
)
def test_no_file_where_the_one_found_would_not_be_the_one_run(project, line):
    _factory, root, _wrote = project
    for name in ("Makefile", "sub/Makefile", "package.json", "sub/package.json", "compose.yaml"):
        (root / name).parent.mkdir(exist_ok=True)
        (root / name).write_text("x\n", encoding="utf-8")
    assert _named_file(root, line, ".") == (None, False)


@pytest.mark.parametrize(
    "line, none",
    [
        ("curl https://example.com/x", True),
        ("wget https://example.com/x", True),
        ("rm -rf build", True),
        ("cp a.txt b.txt", True),
        ("curl.exe https://example.com/x", True),
        ("RM -rf build", True),
        # (round 3: git runs what its settings name - a pager, hooks, an ssh command; gh runs git)
        ("git push origin k-x", False),
        ("git -c 'core.pager=sh evil.sh' log", False),
        ("gh pr list", False),
        # (not plain, wrapped, by its path, or a program that may run the folder's code)
        ("curl https://x && python x.py", False),
        ("env python x.py", False),
        ("timeout 10 curl https://x", False),
        ("./curl https://x", False),
        ("uv run x.py", False),
        ("pip install requests", False),
        ("pip install -r requirements.txt", False),
        ("go run x.go", False),
        ("node x.js", False),
        ("bash -lc 'curl https://x'", False),
        # (told a file of the folder's to read its settings or commands from)
        ("curl -K cfg https://example.com/x", False),
        ("curl -d @cfg https://example.com/x", False),
        # (a value glued to a short option names the file too)
        ("curl -Kcfg https://example.com/x", False),
        ("curl -Tcfg https://example.com/x", False),
        ("wget -icfg https://example.com/x", False),
        ("curl -sS https://example.com/x", True),
        ("git -c core.hooksPath=hooks commit -m x", False),
    ],
)
def test_the_lines_that_run_none_of_the_folders_code(project, line, none):
    _factory, root, _wrote = project
    (root / "cfg").write_text("x\n", encoding="utf-8")
    (root / "hooks").mkdir()
    assert _no_local_code(root, line, ".") is none
