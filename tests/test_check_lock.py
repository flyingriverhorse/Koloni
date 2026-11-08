"""The lock check (.github/scripts/check_lock.py): the lock must satisfy pyproject.toml."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "check_lock.py"
spec = importlib.util.spec_from_file_location("check_lock", SCRIPT)
assert spec and spec.loader
check_lock = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_lock)

PYPROJECT = """[project]
dependencies = ["fastapi>=0.141,<0.142", "uvicorn[standard]>=0.53,<0.54", "pypdf==6.20.0"]
[project.optional-dependencies]
dev = ["pytest-xdist>=3.6,<4"]
"""


def test_a_lock_that_satisfies_pyproject_passes():
    lock = "fastapi==0.141.1\n    # via x\nuvicorn==0.53.0\npypdf==6.20.0\npytest_xdist==3.8.0\n"
    assert check_lock.problems(PYPROJECT, lock) == []


def test_a_bumped_requirement_or_a_missing_package_fails():
    lock = "fastapi==0.140.0\nuvicorn==0.53.0\npypdf==6.20.0\n"
    assert check_lock.problems(PYPROJECT, lock) == [
        "fastapi: locked 0.140.0, pyproject.toml wants <0.142,>=0.141",
        "pytest-xdist: not in requirements-dev.lock"]


def test_the_repositorys_lock_satisfies_its_pyproject():
    assert check_lock.main() == 0
