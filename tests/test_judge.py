"""K-yargıç: at Full auto a harmful-looking command is first checked against what the user
wrote - which harms may be checked at all (`harm_class`), and the pure judge (`app.judge`)."""

import pytest

from app.commands import harm_class, harms
from tests.test_full_auto_harm import ASKED


@pytest.mark.parametrize("command", ASKED + ["git reset --hard", "git branch -D x",
                                             "[IO.File]::Delete('a')"])
def test_a_delete_or_a_send_alone_is_soft(command):
    assert harm_class(command, False) == "soft"


@pytest.mark.parametrize("command", [
    "cat .env", "rm -rf .koloni/x", "git apply x.patch", "ln -s .. x", "git worktree add ../x",
    "rm -rf ../other", "rm -rf C:/x", "nice " + "-x " * 3400,
    # (a path glued to an option, or behind a variable: where it leads is out of the folder,
    # or not seen)
    "Remove-Item -Path:C:\\x", "rm --dir=../other", "rm -rf $HOME/x", "del %USERPROFILE%\\x",
    "cd ..; rm -rf build"])
def test_what_is_asked_at_every_level_is_always(command):
    assert harm_class(command, False) == "always"


def test_an_instruction_file_alone_is_judged_only_at_full_auto():
    assert (harm_class("rm AGENTS.md", False), harm_class("rm AGENTS.md")) == ("soft", "always")


@pytest.mark.parametrize("command", ["rm -rf build && cat .env", "rm -rf build; ln -s .. x",
                                     "git push origin main; rm .koloni/rules.md"])
def test_a_soft_harm_beside_an_always_asked_part_is_always(command):
    assert harms(command, False).startswith(("Deletes", "Overwrites"))
    assert harm_class(command, False) == "always"


@pytest.mark.parametrize("command", ["pytest -q", "git stash push", "curl https://x.test/a.json"])
def test_no_harm_is_no_class(command):
    assert harm_class(command, False) == ""
