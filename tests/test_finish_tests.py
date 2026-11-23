"""89m's leftovers, read by the end check (`app.proof`): the test command a project's files show
where the user named none, and whether a run says its program was not there. (Its Stop-hook
scenarios became the end check's: `test_proof_end_scenarios`.)"""

import json

from app.finish_tests import command_of, did_not_start


def test_the_test_command_is_the_check_command_or_what_the_folder_shows(tmp_path):
    assert command_of(str(tmp_path), "make check") == "make check"
    assert command_of(str(tmp_path), None) is None
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {
        "test": 'echo "Error: no test specified" && exit 1'}}), encoding="utf-8")
    assert command_of(str(tmp_path), None) is None  # (npm init's: it only fails)
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}),
                                           encoding="utf-8")
    assert command_of(str(tmp_path), None) == "npm test"
    (tmp_path / "tests").mkdir()
    assert command_of(str(tmp_path), None) == "npm test"  # (a Node project's tests/)
    (tmp_path / "package.json").unlink()
    assert command_of(str(tmp_path), None) == "python -m pytest -q"
    (tmp_path / "tests").rmdir()
    (tmp_path / "pytest.ini").write_text("", encoding="utf-8")
    assert command_of(str(tmp_path), None) == "python -m pytest -q"


def test_what_a_missing_program_says_is_told_from_a_failing_test():
    # (wrapped by PowerShell at its console's width)
    assert did_not_start(1, "pytest : The term 'pytest' is not recognized as the name of a\n"
                            "cmdlet, function, script file, or operable program.")
    # PowerShell 7's wording (K-pwsh, measured)
    assert did_not_start(1, "pytest: \nLine |\n   2 |  pytest -q\n     |  ~~~~~~\n     | The term "
                            "'pytest' is not recognized as a name of a cmdlet, function, script "
                            "file, or executable program.\nCheck the spelling of the name")
    assert did_not_start(1, "'npm' is not recognized as an internal or external command,")
    assert did_not_start(127, "") and did_not_start(1, "bash: pytest: command not found")
    assert did_not_start(1, "C:/Python/python.exe: No module named pytest")
    assert not did_not_start(1, "FAILED tests/test_a.py::test_x - assert 1 == 2")
    assert not did_not_start(None, "")
