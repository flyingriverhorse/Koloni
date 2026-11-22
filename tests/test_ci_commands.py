"""Kanıtlı bitiş S8, what needs no model: the lint, typecheck and test lines of a project's GitHub
Actions workflows - never an e2e step, an expression, a secret or an install."""

from app import ci_commands

FLOW = """
name: CI
on: [push]
jobs:
  backend:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - name: Install
        run: pip install -e .[dev]
      - name: Lint
        run: ruff check app
      - name: Types
        run: ty check app
      - name: Tests
        run: python -m pytest -q
      - name: Secret
        run: pytest --token ${{ secrets.TOKEN }}
  web:
    runs-on: ubuntu-latest
    steps:
      - name: Unit
        working-directory: ./frontend
        run: npx vitest run
      - name: e2e
        run: npx playwright test
      - name: Tests again
        run: python -m pytest -q
"""


def write(root, text, name="ci.yml"):
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows" / name).write_text(text, encoding="utf-8")


def test_ci_runs_reads_lint_typecheck_and_test_steps_in_their_folders(tmp_path):
    write(tmp_path, FLOW)
    runs, said = ci_commands.ci_runs(tmp_path)
    assert [(one.command, one.cwd) for one in runs] == [
        ("ruff check app", "."), ("ty check app", "."), ("python -m pytest -q", "."),
        ("npx vitest run", "frontend")]  # (the same line in two jobs: once)
    assert "e2e not run: e2e" in said
    assert any("Install" in one and "installs" in one for one in said)
    assert any("Secret" in one and "secrets" in one for one in said)


def test_a_bad_yaml_file_is_said_and_a_change_is_a_new_fingerprint(tmp_path):
    write(tmp_path, "jobs: [unclosed", "bad.yml")
    assert ci_commands.ci_runs(tmp_path) == ([], ["CI file not read: bad.yml does not parse"])
    write(tmp_path, FLOW)
    before = ci_commands.fingerprint(tmp_path)
    write(tmp_path, FLOW + "\n# a comment\n")
    assert ci_commands.fingerprint(tmp_path) != before


def test_a_step_with_another_line_is_not_run(tmp_path):
    write(tmp_path, "jobs:\n  a:\n    steps:\n      - run: |\n          ruff check .\n"
                    "          curl http://example.com\n")
    assert ci_commands.ci_runs(tmp_path)[0] == []
