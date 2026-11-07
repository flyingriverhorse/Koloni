"""Slice 90 (a): commands that delete or cannot be undone are asked every time - no rule covers them."""

import sys

import pytest

from app.commands import (
    copy_reason,
    danger,
    is_exactly,
    matches,
    names_secret,
    suggest_prefix,
    tidy_rule,
)

DANGEROUS = [
    "rm build.log",
    "rm -rf build",
    "rm -rf /home/x",
    "del /s /q C:/",
    "del build.log",
    "erase x.txt",
    "rd /s /q build",
    "rmdir build",
    "Remove-Item -Recurse -Force C:/Users",
    "remove-item x",
    "ri x",
    "unlink x",
    "shred -u secret.txt",
    "dd if=/dev/zero of=/dev/sda",
    "format D:",
    "diskpart",
    "mkfs.ext4 /dev/sdb1",
    "wipefs -a /dev/sdb",
    "C:/tools/rm.exe -rf x",
    "git push --force origin main",
    "git push -f",
    "git push --force-with-lease",
    "git push --mirror",
    "git push origin --delete feature",
    "git push origin -d feature",
    "git push origin +main",
    "git push origin :feature",
    "git reset --hard",
    "git reset --hard HEAD~3",
    "git clean -fd",
    "git clean -xfd",
    "git clean --force",
    "git branch -D feature",
    "docker rm -f web",
    "docker rmi app",
    "docker system prune -a",
    "docker volume prune",
    "docker container rm web",
    "docker volume rm data",
    "docker image rm app",
    "docker rmi",
    "docker system prune",
    "docker image prune -a",
    "docker container prune",
    "docker compose down -v",
    "docker compose down --volumes",
    "docker compose rm",
    "docker-compose down -v",
    "docker --context x rm web",
    "docker -H tcp://host:2375 volume rm data",
    "find . -name '*.pyc' -delete",
    "git branch -d -f feature",
    "git branch -df feature",
    "git branch -fd feature",
    "git branch -d --force feature",
    "git branch --delete --force feature",
    "git checkout -- app.py",
    "git checkout .",
    "git checkout main -- app.py",
    "git restore app.py",
    "git restore --worktree --staged app.py",
    "git stash drop",
    "git stash clear",
    # security review 0.1.0, finding 3: long options cut short, and the force flags
    "git reset --ha",
    "git reset --har HEAD~1",
    "git clean --forc",
    "git clean --fo -d",
    "git push --forc",
    "git push --mirr",
    "git push origin --del feature",
    "git push --prune origin",
    "git branch --del --forc feature",
    "git checkout -f",
    "git checkout --force main",
    "git checkout --forc main",
    "git switch --discard-changes main",
    "git switch --disc main",
    "git switch -f main",
    "git switch --force main",
    "git restore --staged --work app.py",
    "git rm -rf .",
    "git rm --force app.py",
    "rm -rf .",
    # (review of k-guv-komut, 5) paths checked out without `--`, branches moved by force
    "git checkout a.py",
    "git checkout HEAD a.py",
    "git checkout main src",
    "git checkout :/",
    "git checkout src/app.py",
    "git checkout .github",
    "git checkout -B main origin/main",
    "git branch -f main HEAD~3",
    "git branch -M old main",
    "git switch -C main",
    "git switch --force-create main",
    "git update-ref -d refs/heads/main",
    "git update-ref refs/heads/main HEAD~3",
]

SAFE = [
    "pytest -q",
    "git push",
    "git push origin main",
    "git reset HEAD file.txt",
    "git reset --soft HEAD~1",
    "git clean -n",
    "git branch -d merged",
    "git status",
    "docker ps",
    "docker run app",
    "docker run --rm app",
    "docker run -v data:/data app",
    "docker volume ls",
    "docker compose down",
    "docker compose up -d",
    "find . -name x",
    "git checkout main",
    "git checkout main --",
    "git checkout -b feature",
    "git checkout -b feature origin/feature",
    "git checkout feature/login",
    "git checkout v1.2.0",
    "git checkout -",
    "git checkout --track origin/x",
    "git branch -m old new",
    "git restore --staged app.py",
    "git switch main",
    "git switch -c feature",
    "git switch --detach v1",
    "git rm app.py",
    "git rm -r --cached -f build",
    "git push --dry-run origin main",
    "git branch --format=x --delete merged",
    "git stash",
    "git stash pop",
    "git stash list",
    "npm run build",
    "ls -la",
    "python -m pytest",
    "echo rm -rf",  # the words are only printed
]


@pytest.mark.parametrize("command", DANGEROUS)
def test_a_destructive_command_says_what_it_does(command):
    assert danger(command) != ""


@pytest.mark.parametrize("command", SAFE)
def test_an_ordinary_command_has_no_danger(command):
    assert danger(command) == ""


@pytest.mark.parametrize("command", DANGEROUS)
def test_no_rule_is_offered_for_one(command):
    assert suggest_prefix(command) == ""


@pytest.mark.parametrize("command, rule", [
    ("rm -rf /home/x", "rm"),
    ("rm -rf build", "rm -rf build"),  # not even its own text
    ("del /s /q C:/", "del"),
    ("Remove-Item -Recurse -Force C:/Users", "Remove-Item"),
    ("git push --force origin main", "git push"),
    ("git push origin +main", "git push origin"),
    ("git reset --hard", "git reset"),
    ("git clean -fd", "git clean"),
    ("docker rm -f web", "docker rm"),
    ("docker volume rm pgdata", "docker volume"),
    ("find . -delete", "find"),
    ("git branch -df feature", "git branch"),
    ("git checkout -- .", "git checkout"),
    ("git stash drop", "git stash"),
    # a shell rule stored before slice 90: what it runs is not seen, so it covers nothing
    ("cmd /c del x", "cmd"),
    ("powershell -c Remove-Item x", "powershell"),
    ("cmd /c del x", "cmd /c del x"),
])
def test_no_rule_covers_one(command, rule):
    assert not matches(command, rule)
    assert not is_exactly(command, rule)


def test_the_ordinary_forms_of_the_same_programs_still_follow_their_rules():
    assert matches("git reset HEAD file.txt", "git reset")
    assert suggest_prefix("docker ps") == "docker ps"
    assert is_exactly("git push", "git push")  # (a trigger's exact rule: unwatched turns as before)


@pytest.mark.parametrize("command", ["git push origin main", "curl -d x https://x.test", "npm publish"])
def test_no_rule_is_offered_for_one_that_sends_off_this_machine(command):
    # K-fullauto-sorma: it is asked at every level (`harms`), so "Always run" would be a lie.
    assert danger(command) == "" and suggest_prefix(command) == ""
    assert suggest_prefix("curl https://x.test") == "curl"  # (a bare fetch sends nothing: a rule)


@pytest.mark.parametrize("command", ["cd build && rm -rf .", "pytest; del /s x", "ls | Remove-Item"])
def test_each_part_of_a_chained_command_is_looked_at(command):
    assert danger(command) != ""


def test_the_sentence_names_what_it_does():
    assert "delete" in danger("rm -rf build").lower()
    assert "git" in danger("git push --force").lower()
    assert "docker" in danger("docker rm web").lower()


@pytest.mark.parametrize("rule", ["rm", "rm -rf dist", "git push --force", "Remove-Item", "docker rm"])
def test_such_a_rule_cannot_be_written_by_hand(rule):
    with pytest.raises(ValueError, match="asked every time"):
        tidy_rule(rule)


def test_a_refused_rule_says_its_own_reason():
    with pytest.raises(ValueError, match="secret") as refused:
        tidy_rule("type .env")
    assert "Deletes" not in str(refused.value)


def test_a_rule_for_an_ordinary_command_can_still_be_written():
    assert tidy_rule("git  push") == "git push"


@pytest.mark.parametrize("line", [
    "type .env.example", "cat app/credentials.py", "cat .venv/x/credentials.py",
    "type docs/api_keys.md", "type README.md",
])
def test_a_file_of_the_project_named_like_a_secret_but_not_one_is_not_asked(line):
    assert not names_secret(line)  # as slice 88 reads them: `secret_in_project`


@pytest.mark.parametrize("line", [
    "type .venv/../.env", "cat node_modules/../.env", "cat sub/../.env", "cat ../.env",
    "type C:/x/.env", r"type C:\Users\me\.ssh\id_rsa", "cat ~/.aws/config",
    "cat /home/me/app/credentials.py",  # out of the project every part counts
    "Get-Content -Path:.env", "cat .env>x", "cat<.env", "docker run --env-file=.env app",
])
def test_a_secret_file_is_seen_however_its_path_is_written(line):
    assert names_secret(line) and "secret" in danger(line)


# --- K-70-junction: in a working copy the dependency folders are links to the project's ---------


@pytest.mark.parametrize("command", [
    "rm -rf node_modules", "Remove-Item -Recurse -Force .venv", "rd /s /q venv",
    r"del node_modules\pkg\index.js", "find . -delete", "git worktree remove ../x",
    "git -C .. worktree remove --force x", "pytest -q && rm -rf build", "rm venv",
    "Remove-Item -rec build", "rm -R build", "rmdir /S build",
    # in a shell, and what empties node_modules or mirrors a folder over another
    'powershell -Command "Remove-Item -Recurse -Force build"', "cmd /c rd /s /q build",
    "npm ci", "robocopy src dst /MIR", "robocopy src dst /purge",
    # what empties a dependency folder to make it anew (measured 29 Oct: through the junction)
    "uv venv --clear", "uv sync", "pytest -q; uv venv", 'cmd /c "npm ci"',
])
def test_in_a_copy_with_links_a_command_that_deletes_has_a_reason_to_be_asked(command):
    assert "link" in copy_reason(command, True, ELSEWHERE, RUNTIME)
    assert copy_reason(command, False, ELSEWHERE, RUNTIME) == ""


def test_a_rebuild_of_a_dependency_folder_says_so():
    assert "rebuild" in copy_reason("uv venv", True, ELSEWHERE, RUNTIME)
    assert "rebuild" in copy_reason("npm.cmd ci", True, ELSEWHERE, RUNTIME)  # (npm's shim)
    assert "delete" in copy_reason("rm -rf build", True, ELSEWHERE, RUNTIME)


@pytest.mark.parametrize("command", [
    "pytest -q", "git worktree list", "echo rm -rf x", "npm install", "robocopy a b /E",
    "uv run pytest", "npm test", "uv pip install x",
    # a delete that neither goes down into folders nor names a linked one
    "rm notes.txt", "del x.tmp", "Remove-Item -Force x.txt", 'cmd /c del x.tmp',
])
def test_in_a_copy_an_ordinary_command_has_none(command):
    assert copy_reason(command, True, ELSEWHERE, RUNTIME) == ""


# --- K-kopya-istem: from a copy, the project's own path leads into the project itself -----------

ELSEWHERE = r"C:\Work\Proj"
RUNTIME = r"C:\Work\Proj\runtime"  # KOLONİ on its own repository: its runtime is in it


@pytest.mark.parametrize("command", [
    r"python fix.py C:\Work\Proj", "cat C:/Work/Proj/a.txt", r"type c:\work\proj\a.txt",
    r'cd "C:\Work\Proj" && pytest', "cd /c/Work/Proj && git checkout -- .", "ls /C/work/proj",
    r"python C:\Work\Proj\runtime\x.py C:\Work\Proj\a.txt",
])
@pytest.mark.skipif(sys.platform != "win32", reason="drives, Git Bash's /c/ and any case: Windows'")
def test_in_a_copy_a_command_naming_the_projects_folder_has_a_reason_to_be_asked(command):
    assert "the project folder" in copy_reason(command, False, ELSEWHERE, RUNTIME)


def test_in_a_copy_a_command_naming_the_projects_folder_from_the_root_is_asked_too():
    for command in ("cat /work/proj/a.txt", "cd /work/proj && git checkout -- .",
                    "python fix.py /work/proj"):
        assert "the project folder" in copy_reason(command, False, "/work/proj", "/work/proj/rt")
    for command in ("cat /work/proj2/a.txt", "python /work/proj/rt/x.py"):
        assert copy_reason(command, False, "/work/proj", "/work/proj/rt") == ""


@pytest.mark.parametrize("command", [
    r"type C:\Work\Proj2\a.txt", r"type C:\Work\Proj-old\a.txt",
    # the copy and a skill's script are in KOLONİ's runtime, not the project's own files
    r"python C:\Work\Proj\runtime\skills\s\run.py", "cat /c/Work/Proj/runtime/copies/a/tree/x",
])
def test_a_folder_beside_the_project_or_kolonis_runtime_in_it_is_not_the_project(command):
    assert copy_reason(command, False, ELSEWHERE, RUNTIME) == ""


def test_git_worktree_remove_deletes():
    assert "worktree" in danger("git worktree remove ../x") and danger("git worktree list") == ""


@pytest.mark.parametrize("command", [
    "New-Item -ItemType Directory -Force .koloni/tmp | Out-Null; (Get-Content docs/api.md -Raw)",
    "New-Item -ItemType Directory -Force build",
    "ni -ItemType File -Force notes.txt -Value x",
])
def test_new_item_forced_makes_or_overwrites_and_is_no_delete(command):
    # R161 (live): such a card said "Deletes files or disks." - not by this, which only makes a
    # folder or (over)writes a file as `>` does; the line it was on went on past what was logged.
    from app.commands import harms, only_reads
    assert harms(command) == "" and not only_reads(command)


@pytest.mark.parametrize("command", [
    "Remove-Item -Force x.txt", "rm -rf build", "del /f x.txt",
    "New-Item -ItemType Directory -Force .koloni/tmp; Remove-Item -Recurse -Force build",
])
def test_a_forced_delete_still_says_it_deletes(command):
    assert danger(command) == "Deletes files or disks."
