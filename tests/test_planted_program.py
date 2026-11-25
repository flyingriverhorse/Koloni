"""Full auto's judge reads the program a command runs where an agent wrote it (`planted_program`):
the script an interpreter or a shell is handed, or the program named by its path - one an agent's
write on record still stands as, in the project."""

import sys
from pathlib import Path

import pytest

from app.agent.risk_judge_mixin import planted_program
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
    "line", ['python -c "print(1)"', 'node -e "1"', "bash -c 'x'", "pytest -q", "gen.py"]
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
