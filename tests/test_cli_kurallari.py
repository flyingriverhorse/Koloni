"""The CLIs' own deterministic rules beside KOLONİ's (the comparison of 27 Nov 2026): lines Claude
Code still asks of that KOLONİ took for reads, git below the project's root at Full auto, and the
files Claude Code protects that KOLONİ did not."""

import pytest

from app import commands, risk_judge
from app.agent import _command_names
from app.commands import _looks_only, only_reads, only_searches, reaches_network, web_off_reason
from app.project_view import standing
from app.proof import may_write
from app.read_edges import globs_an_option
from tests.fakes import Script
from tests.test_agent_commands import cmd
from tests.test_chat_flow import text
from tests.test_full_auto_judge import go, said
from tests.test_judge_scenarios import judging  # noqa: F401  (a fixture)

READERS = (only_reads, only_searches, _looks_only, commands._reads, commands.only_looks)

# A wildcard sh may expand to a file named like an option: a file `-delete` makes `find *` a
# delete, `--pre=x` makes `rg foo *` run x - as the word starts (`*`, `''*`, `\-*`, `{a,-}*`) or
# as it finishes an option's name (`-*`, `--p*`).
GLOBS = [
    "find *",
    "find * -name x",
    "rg foo *",
    "rg foo *.py",
    "grep -r foo *",
    "cat *",
    "ls *",
    "cat ''*",
    "rg x -*",
    "rg x --p*",
    "find . -name *.py",
    "rg -g *.py foo",
    "ls {a,-}*",
    "cat \\-*",
    "head -n 5 ?.log",
    "ls [-a]*",
    "rg x \\\n*",  # (a line continued: `rg x *`)
    'rg foo .github "\\"" *',  # (sh's `\"` in double quotes ends none)
]
# bash's /dev/tcp and /dev/udp: the internet, by a redirection (and as the shell joins the word)
NET = [
    "cat < /dev/tcp/example.com/80",
    "exec 3<>/dev/tcp/example.com/80",
    "echo hi > /dev/udp/10.0.0.1/53",
    'cat </dev/t""cp/h/80',
    "grep x < /dev/tcp/h/80",
    # (a part after /dev/ the shell builds as it runs)
    "t=tcp; cat </dev/$t/h/80",
    "cat </dev/${t}/h/80",
    "exec 3<>/dev/$'tcp'/h/80",
    "cat < $'/dev/tc\\x70/h/80'",
]
# A line that sets IFS or PATH: what runs, or how its words split, is not what is written.
SETS = [
    "IFS=x cat a.txt",
    "PATH=. cat a.txt",
    "PATH=. rg foo src",
    "IFS=x find .",
    "export PATH=.; cat a.txt",
    "export PATH=. && ls",
    "env PATH=. cat a.txt",
    "PATH=.\ncat a.txt",
    "IFS=, ; cat a.txt",
]
# git after a change of folder: a repository shaped there - a bare one, no `.git` name - sets the
# programs git runs ("bare repository attacks", Claude Code's)
CD_GIT = [
    "cd sub && git status",
    "cd sub; git log",
    "pushd sub; git log",
    "Set-Location sub; git status",
    "cd sub\ngit log",
    "rg x; cd sub && git log",
    "rg x && git log",
    # (a `;` out of quotes: PowerShell's `\;` is one, and sh's `\"` opens no quote)
    "rg a\\;b .github",
    'rg \\"a;b" .github',
]


@pytest.mark.parametrize("line", GLOBS + NET + SETS + CD_GIT)
def test_a_line_claude_code_still_asks_of_is_no_read_look_or_search(line):
    assert not [reads.__name__ for reads in READERS if reads(line)], line


@pytest.mark.parametrize("line", GLOBS)
def test_a_wildcard_that_may_be_an_option_is_told(line):
    assert globs_an_option(line)


@pytest.mark.parametrize(
    "line",
    [
        "rg foo src/*.py",
        "rg -g '*.py' foo",
        "rg --glob=*.py foo",
        "find . -name '*.py'",
        "find .github -name '*.yml'",
        "rg 'a*' src",
        "rg -e '[-x]' src",
        "rg --files --hidden -g '!**/.koloni/**'",
        "rg TODO --glob=!.koloni/** --iglob '!.github'",
    ],
)
def test_a_wildcard_that_expands_to_no_option_leaves_a_search_a_search(line):
    assert not globs_an_option(line) and only_searches(line) and _looks_only(line)


@pytest.mark.parametrize("line", ["ls ./*", 'cat "*"', "cat src/a*.txt", "ls .koloni/worktrees/*"])
def test_a_wildcard_that_expands_to_no_option_leaves_a_look_a_look(line):
    assert not globs_an_option(line) and _looks_only(line)


@pytest.mark.parametrize(
    "line", ["cat a.txt", "ls src", "git status", "head -n 5 a.txt", "git log -3", "ls"]
)
def test_a_plain_read_stays_a_read(line):
    assert only_reads(line) and commands._reads(line) and commands.only_looks(line)
    assert reaches_network(line) == ""


@pytest.mark.parametrize(
    "line", ["rg foo src", "grep -rn TODO .github", "rg --files -g AGENTS.md", "ag foo .claude"]
)
def test_a_plain_search_stays_a_search(line):
    assert only_searches(line) and commands._reads(line) and commands.names_standing(line) == ""


@pytest.mark.parametrize(
    "line",
    ["rg '&&' .github/workflows", "grep -rn ';' .github", "rg -F 'x;y' .", 'rg "a&b" .claude'],
)
def test_a_quoted_semicolon_or_ampersand_leaves_a_search_a_search(line):
    # (the review: each was a card at every level on this branch, and a line that may write)
    assert only_searches(line) and commands.names_standing(line) == "" and not may_write(line)


BS = "\\"  # (one backslash)


@pytest.mark.parametrize(
    "line",
    [
        # sh: a backslash's `"` does not end "…", so the `;` after "\"" chains (the re-check's)
        f'rg "{BS}"" ; cp evil.yml .github/workflows/ci.yml ; echo "{BS}""',
        # PowerShell: a backslash escapes nothing - `\'` opens a quote
        f'rg {BS}\'a \' "\'"; Copy-Item evil.xml .idea/runConfigurations/x.xml; ""',
        # PowerShell's typographic quotes end a quote too
        "rg 'a’; Copy-Item evil.xml .idea/runConfigurations/x.xml; ‘'",
        'rg "a”; Copy-Item evil.yml .github/workflows/ci.yml; “"',
    ],
)
def test_a_semicolon_in_a_line_that_is_not_simple_chains_a_write_that_asks(line):
    assert not only_searches(line)
    assert commands.names_standing(line) in (".github", ".idea")
    assert commands.standing_asked(line, False)  # (Full auto too)


@pytest.mark.parametrize("line", NET)
def test_bashs_dev_tcp_reaches_the_internet_and_asks_with_web_off(line):
    assert reaches_network(line).startswith("/dev/")
    assert "/dev/" in web_off_reason(line, ["http_request"])


@pytest.mark.parametrize(
    "line",
    ["cat src/dev/tcp/a.py", "ls ./dev/udp", "cat mydev/tcp/x", "cat /dev/null", "ls /dev/fd/3"],
)
def test_a_project_path_with_dev_tcp_in_it_reaches_nothing(line):
    assert reaches_network(line) == ""


def test_git_below_the_root_is_neither_a_read_nor_ordinary_to_the_judge():
    assert risk_judge.git_below("git status", "sub")
    assert risk_judge.git_below("git log -3", "a/b")
    assert not risk_judge.git_below("git status", ".")
    assert not risk_judge.git_below("git status", "")
    # (where it runs is not known - Claude Code's PowerShell keeps a Set-Location: not the root)
    assert risk_judge.git_below("git status", None)
    assert not risk_judge.git_below("cat a.txt", "sub")


def test_a_root_shaped_as_a_bare_repository_is_no_root_to_git(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert not risk_judge.git_below("git status", ".", tmp_path)
    assert commands.reads_here("git status", tmp_path, True)
    (tmp_path / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
    (tmp_path / "objects").mkdir()
    assert risk_judge.git_below("git status", ".", tmp_path)
    assert not commands.reads_here("git status", tmp_path, True)
    assert commands.reads_here("cat a.txt", tmp_path, True)  # (only git's)
    (tmp_path / ".git").mkdir()  # (a .git there: git takes that one)
    assert not risk_judge.git_below("git status", ".", tmp_path)


@pytest.mark.parametrize(
    "shape",
    [
        {"objects": "a file"},  # (git ran core.fsmonitor here too: the re-check's)
        {"commondir": "common", "common/config.worktree": "x"},
    ],
)
def test_any_head_with_no_git_folder_is_no_root_to_git(tmp_path, shape):
    for rel, body in {"HEAD": "ref: refs/heads/main", **shape}.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body, encoding="utf-8")
    assert risk_judge.git_below("git status", ".", tmp_path)
    assert not commands.reads_here("git status", tmp_path, True)


@pytest.mark.judge
@pytest.mark.no_po
@pytest.mark.parametrize("line", ["git status", "git log -3"])
def test_at_full_auto_git_below_the_root_is_put_to_the_judge(
    judging,  # noqa: F811
    wait_run,
    project_dir,
    line,
):
    (project_dir / "sub").mkdir()
    client, _lead, judge, executor = judging(
        [cmd(line, cwd="sub"), text("done")], [said("fine")], [Script([])]
    )
    _, cid, run_id = go(client, project_dir)
    (ran,) = wait_run(client, cid, run_id)["commands"]
    assert ran["status"] == "exited" and executor.started[0][0] == line
    assert len(judge.calls) == 1 and ran["judged"]["verdict"] == "fine"


PROTECTED = {
    "echo x > .cargo/config.toml": ".cargo",
    "cp x .idea/workspace.xml": ".idea",
    "echo '{}' > .devcontainer/devcontainer.json": ".devcontainer",
    "echo '{}' > .devcontainer.json": ".devcontainer.json",
    "sed -i s/a/b/ .gitmodules": ".gitmodules",
    "echo x > .mvn/jvm.config": ".mvn",
    "echo x > gradle/wrapper/gradle-wrapper.properties": "gradle-wrapper.properties",
    "cp x.jar gradle/wrapper/gradle-wrapper.jar": "gradle-wrapper.jar",
    "echo x >> .bazelrc": ".bazelrc",
    "echo 9.0.0 > .bazelversion": ".bazelversion",
}


@pytest.mark.parametrize("line, name", PROTECTED.items())
def test_a_command_writing_one_of_claude_codes_protected_names_asks_at_every_level(line, name):
    assert commands.names_standing(line) == name and commands.danger(line)
    assert commands.standing_asked(line, False) == name  # (Full auto too)


@pytest.mark.parametrize(
    "line",
    [
        "./gradlew test",
        "gradle test",
        "./mvnw verify",
        "mvn -q test",
        "cargo test",
        "bazel build //...",
        "cat .gitmodules",
        "rg foo .idea",
        "git submodule status",
    ],
)
def test_running_the_build_or_reading_its_settings_names_none(line):
    assert commands.names_standing(line) == ""


def test_the_write_audit_looks_at_them_and_lets_a_submodule_line_write_gitmodules(tmp_path):
    looked = {
        ".cargo/config.toml",
        ".gitmodules",
        "gradle/wrapper/gradle-wrapper.properties",
    }
    # (.idea's is not looked at: the IDE rewrites workspace.xml itself - asked by name only)
    for rel in [*looked, "src/a.py", "gradlew", ".idea/workspace.xml", ".idea/dataSources/x"]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x", encoding="utf-8")
    assert set(standing(tmp_path)) == looked
    # An approved `git submodule` line writes .gitmodules as git's own: it stands, as git's
    # config does; any other git line's change there is a card, as before.
    assert _command_names("git submodule add https://x lib", True, False)[0] == {
        ".git/config",
        ".gitmodules",
    }
    assert _command_names("git push -u origin x", True, False)[0] == {".git/config"}
    assert _command_names("git submodule add https://x lib", False, False)[0] == set()


@pytest.mark.parametrize(
    "line, stands",
    [
        ("git submodule add https://x lib", {".git/config", ".gitmodules"}),
        ("git submodule set-url lib https://y", {".git/config", ".gitmodules"}),
        ("git submodule -q set-branch -b main lib", {".git/config", ".gitmodules"}),
        ("git submodule update --init", {".git/config"}),
        ("git submodule sync", {".git/config"}),
        ("git submodule deinit lib", {".git/config"}),
        # (the review: by git's own sub-command and verb, never a word of the line)
        ("git checkout fix-submodule", {".git/config"}),
        ("git switch feat/submodule", {".git/config"}),
        ("git checkout main -- docs/submodule.md", {".git/config"}),
        # (foreach runs any command - core.fsmonitor in .git/config would stand)
        ("git submodule foreach 'git config core.fsmonitor ../w.sh'", set()),
        ("git submodule status", set()),
        ("git submodule summary", set()),
        ("git submodule", set()),
        ("git submodule update", set()),
        # (a chain with a part that runs a command it is handed lets nothing stand)
        ("git submodule add https://x lib; git submodule foreach 'python ../w.py'", set()),
        ("git remote add o https://x; git rebase -x 'python w.py' main", set()),
        ("git init && git rebase --exec=make main", set()),
        ("git init; git bisect run make", set()),
    ],
)
def test_what_a_git_line_lets_stand_is_by_its_own_verb(line, stands):
    assert _command_names(line, True, False)[0] == stands
