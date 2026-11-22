"""Kanıtlı bitiş S9, what needs no model: the coverage tool a project already has, the report flags
its whole-suite run gets, and the share of the changed lines its report says the tests ran."""

import json
import sys

from app import coverage


def test_tool_of_each_kind_and_none(tmp_path):
    assert coverage.tool_of(tmp_path, "python -m pytest -q") is None  # (nothing installed)
    (tmp_path / "pyproject.toml").write_text('[project.optional-dependencies]\ndev = ["pytest-cov"]\n',
                                            encoding="utf-8")
    assert coverage.tool_of(tmp_path, "python -m pytest -q") == "pytest-cov"
    assert coverage.tool_of(tmp_path, "python -m pytest -q | tail -1") is None  # (exit masked)
    web = tmp_path / "web"
    web.mkdir()
    (web / "package.json").write_text(json.dumps({
        "scripts": {"test": "vitest run"}, "devDependencies": {"@vitest/coverage-v8": "^3"}}),
        encoding="utf-8")
    assert coverage.tool_of(web, "npm test") == "vitest"
    assert coverage.tool_of(web, "npx vitest run") == "vitest"
    assert coverage.tool_of(web, "make test") is None  # (a node runner's only)
    (web / "package.json").write_text(json.dumps({
        "scripts": {"test": "mocha"}, "devDependencies": {"c8": "^9"}}), encoding="utf-8")
    assert coverage.tool_of(web, "npm test") is None  # (no local bin: never a download)
    (web / "node_modules" / ".bin").mkdir(parents=True)
    (web / "node_modules" / ".bin" / ("c8.cmd" if sys.platform == "win32" else "c8")).write_text("")
    assert coverage.tool_of(web, "npm test") == "c8"


def test_with_coverage_commands():
    out = "C:/p/.koloni/tmp/coverage-x" if sys.platform == "win32" else "/p/.koloni/tmp/coverage-x"
    q = (lambda one: f'"{one}"') if sys.platform == "win32" else (lambda one: one)
    assert coverage.with_coverage("python -m pytest -q", "pytest-cov", out) == (
        f"python -m pytest -q --cov=. --cov-report=json:{q(out + '/coverage.json')}")
    assert coverage.with_coverage("npm test", "vitest", out) == (
        f"npm test -- --coverage --coverage.reporter=json --coverage.reportsDirectory={q(out)}")
    assert coverage.with_coverage("pnpm test", "vitest", out).startswith("pnpm test --coverage ")
    assert coverage.with_coverage("npx vitest run", "vitest", out).startswith(
        "npx vitest run --coverage ")
    assert coverage.with_coverage("npm test", "c8", out) == (
        f"npx --no c8 --reporter=json --report-dir {q(out)} npm test")


def test_covered_from_coverage_py_json(tmp_path):
    data = {"files": {"app/a.py": {"executed_lines": [1, 2, 5], "missing_lines": [3, 4]},
                      "app/b.py": {"executed_lines": [1], "missing_lines": []}}}
    said = coverage.changed_lines_covered(tmp_path, data, "pytest-cov",
                                          {"app/a.py": [2, 3, 4, 9], "docs/x.md": [1]})
    assert said == coverage.Covered(33, {"app/a.py": [3, 4]})  # (9 no test could run: out)
    # (a part's run names its files from its folder)
    said = coverage.changed_lines_covered(tmp_path, {"files": {"a.py": data["files"]["app/a.py"]}},
                                          "pytest-cov", {"app/a.py": [2, 3]}, "app")
    assert said == coverage.Covered(50, {"app/a.py": [3]})


def test_covered_from_istanbul_json(tmp_path):
    path = str(tmp_path / "src" / "a.ts")
    data = {path: {"path": path, "statementMap": {
        "0": {"start": {"line": 1}}, "1": {"start": {"line": 2}}, "2": {"start": {"line": 3}}},
        "s": {"0": 4, "1": 0, "2": 1}}}
    said = coverage.changed_lines_covered(tmp_path, data, "vitest", {"src/a.ts": [1, 2, 3]})
    assert said == coverage.Covered(67, {"src/a.ts": [2]})


def test_a_report_is_read_only_under_the_scratch_and_size_capped(tmp_path, monkeypatch):
    inside = tmp_path / ".koloni" / "tmp" / "coverage-1"
    inside.mkdir(parents=True)
    (inside / "coverage.json").write_text('{"files": {}}', encoding="utf-8")
    assert coverage.report(tmp_path, inside, "pytest-cov") == {"files": {}}
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "coverage.json").write_text('{"files": {}}', encoding="utf-8")
    assert coverage.report(tmp_path, outside, "pytest-cov") is None
    monkeypatch.setattr(coverage, "MOST_REPORT", 3)
    assert coverage.report(tmp_path, inside, "pytest-cov") is None


def test_ranges():
    assert coverage.ranges([20, 12, 13, 14, 3]) == "3, 12-14, 20"


def test_a_line_with_kolonis_flags_is_known_by_its_command():
    for out in (".koloni/tmp/coverage-0123456789ab", "/p/q/.koloni/tmp/coverage-0123456789ab",
                "C:/p/.koloni/tmp/coverage-0123456789ab"):
        for command, tool in [("python -m pytest -q", "pytest-cov"),
                              ("npm test -- --run", "vitest"), ("npx vitest run", "vitest"),
                              ("npm test", "c8")]:
            assert coverage.unflagged(coverage.with_coverage(command, tool, out)) == command
    # (review, 22 Nov: KOLONİ's exact form only - shell syntax, `..`, another folder stay)
    for line in ["pytest --cov=. --cov-report=json:out.json",
                 "pytest -q --cov=. --cov-report=json:.koloni/tmp/coverage-x>o.txt;true",
                 "pytest -q --cov=. --cov-report=json:.koloni/tmp/coverage-x||true",
                 "pytest -q --cov=. --cov-report=json:.koloni/tmp/coverage-x/../../../x;exit",
                 "pytest -q --cov=. --cov-report=json:.koloni/tmp/coverage-0123456789ab/"
                 "coverage.json;true",
                 "pytest -q --cov=. --cov-report=json:/a/../.koloni/tmp/coverage-0123456789ab/"
                 "coverage.json",
                 "pytest -q --cov=. --cov-report=json:$(x)/.koloni/tmp/coverage-0123456789ab/"
                 "coverage.json"]:
        assert coverage.unflagged(line) == line, line


def test_a_report_that_breaks_the_reader_is_none(tmp_path):
    inside = tmp_path / ".koloni" / "tmp" / "coverage-1"
    inside.mkdir(parents=True)
    (inside / "coverage.json").write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
    assert coverage.report(tmp_path, inside, "pytest-cov") is None  # (RecursionError: not read)
    odd = {"files": {"a.py": {"executed_lines": [[1], "x", 2], "missing_lines": 3}, "b.py": 4}}
    assert coverage.changed_lines_covered(tmp_path, odd, "pytest-cov", {"a.py": [2]}) == (
        coverage.Covered(100, {}))
    odd = {"x": {"statementMap": {"0": 5, "1": {"start": 6}}, "s": [], "path": 7}}
    assert coverage.changed_lines_covered(tmp_path, odd, "vitest", {"x": [1]}) == (
        coverage.Covered(None, {}))


def test_the_coverage_settings_mark_changes_with_them(tmp_path):
    before = coverage.config_mark(tmp_path)
    (tmp_path / ".coveragerc").write_text("[report]\nfail_under = 90\n", encoding="utf-8")
    assert coverage.config_mark(tmp_path) != before
