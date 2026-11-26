"""What a turn nobody watches was held to that is not only its own: which providers work with tools
of their own, the files that give later turns leave or run by themselves (`stands_over_later_turns`),
and a conversation's allow list put together by hand. (Kept from the trigger tests, slice 18a.)"""

import os
import subprocess
from pathlib import Path

import pytest

from app import agent as agent_module
from app.db.models import Provider
from app.providers import HTTP_KINDS, MODES, Providers, works_with_own_tools
from app.workspace import NOT_WRITTEN_UNATTENDED, Workspace, stands_over_later_turns
from tests.fakes import Script, ScriptedExecutor, ScriptedModel
from tests.test_chat_flow import text
from tests.test_spawn import call, step
from tests.turn_helpers import allow, setup, until

# --- every kind of provider, every way it runs --------------------------------------------

# What each is in a turn nobody is watching, as the lead and as a sub-agent's provider
# alike:
#   "koloni"   it works with KOLONİ's tools: each goes through the gate (`_run_call`)
#   "refused"  it works with tools of its own: it is not started at all. That it asks
#              KOLONİ first (Claude Code) or itself refuses what would change something
#              (agy that reads) does not make it one that can be held: it reads where it
#              likes, and asks only when it chooses to.
IN_AN_UNATTENDED_TURN = {
    ("openai_compat", None): "koloni",
    ("anthropic", None): "koloni",
    ("claude_cli", "session"): "koloni",
    ("claude_cli", "step"): "koloni",
    ("claude_cli", "native"): "refused",
    ("codex_cli", "session"): "koloni",
    ("codex_cli", "native"): "refused",
    ("copilot_cli", "session"): "koloni",
    ("copilot_cli", "native"): "refused",
    ("agy_cli", "reads"): "refused",
    ("agy_cli", "native"): "refused",
}


def test_the_table_names_every_kind_and_every_way_it_runs():
    every = {(kind, mode) for kind, modes in MODES.items() for mode in modes}
    every |= {(kind, None) for kind in HTTP_KINDS}
    assert set(IN_AN_UNATTENDED_TURN) == every


@pytest.mark.parametrize("kind, mode", list(IN_AN_UNATTENDED_TURN))
def test_what_each_kind_of_provider_is_in_a_turn_nobody_is_watching(settings, kind, mode):
    row = Provider(
        id="p",
        name="P",
        kind=kind,
        mode=mode,
        base_url="http://127.0.0.1:9/v1",
        api_key="k",
        options={},
    )
    client = Providers(settings)._build(row, None)
    refused = IN_AN_UNATTENDED_TURN[kind, mode] == "refused"
    # every client that works with tools of its own says so, and no other does: a
    # session or one step at a time has nothing of its own that acts
    assert bool(getattr(client, "native", False)) is refused
    assert works_with_own_tools(row) is refused
    # the one question the runner asks before a lead or a sub-agent starts: by the
    # client, and by the provider as the user set it up - whichever client stands in
    held = agent_module.AgentRunner._cannot_be_held
    assert held(client) is refused
    assert held(ScriptedModel([]), row) is refused
    assert held(None, row) is refused
    assert held(ScriptedModel([])) is False and held(None) is False


# --- files that give later turns leave, or run by themselves ----------------------------------


def junction(link: Path, target: Path) -> None:
    """A directory junction, which Windows lets any account make; elsewhere a symlink.
    Skips the test where neither can be made."""
    try:
        if os.name == "nt":
            made = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                check=False,
            )
            if made.returncode != 0:
                raise OSError(made.stderr.decode(errors="replace"))
        else:
            link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"this account may not make links: {exc}")


@pytest.mark.parametrize(
    "path",
    [
        ".claude/settings.json",
        ".claude/agents/free.md",
        ".claude/hooks/x.sh",
        ".codex/config.toml",
        ".qoder/rules.md",
        ".agy/settings.json",
        ".git/config",
        ".git/hooks/pre-commit",
        ".github/workflows/ci.yml",
        ".vscode/tasks.json",
        ".husky/pre-commit",
        ".pre-commit-config.yaml",
        "sub/.Pre-Commit-Config.yaml.",
        ".lintstagedrc",
        ".lintstagedrc.json",
        "lefthook.yml",
        "Lefthook.YAML",
        ".lefthook.yml",
        "lefthook-local.yml",
        "lint-staged.config.mjs",
        ".simple-git-hooks.json",
        "simple-git-hooks.js",
        ".mcp.json",
        ".claude.json",
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        ".koloni/rules.md",
        ".koloni/settings.json",
        ".KOLONI./recipes/x.json",
        # at any depth, in any case, with either slash
        "sub/deep/.claude/x",
        "sub/AGENTS.md",
        "sub\\.git\\config",
        ".GIT/config",
        "Agents.MD",
        ".Mcp.Json",
        "pkg/.VSCode/settings.json",
        # as Windows would open them all the same: a dot or a space at the end, a stream
        ".git./config",
        ".claude /x",
        "AGENTS.md.",
        "AGENTS.md ",
        "CLAUDE.md::$DATA",
        ".git::$INDEX_ALLOCATION/config",
        # by another way round
        "./.git/config",
        "src/../.git/config",
        "src/../AGENTS.md",
        # an environment's .pth: it runs at every start of its Python
        ".venv/Lib/site-packages/x.pth",
        "env/lib/python3.12/site-packages/X.PTH.",
        ".venv/lib/site-packages/a.pth::$DATA",
    ],
)
def test_what_gives_later_turns_leave_or_runs_by_itself_is_told_by_its_path(tmp_path, path):
    (tmp_path / "src").mkdir()
    assert stands_over_later_turns(Workspace(tmp_path), path), path


@pytest.mark.parametrize(
    "path",
    [
        "notes/ok.txt",
        "hello.py",
        "src/claude.py",
        "docs/AGENTS.md.txt",
        "docs/agents.md.bak",
        "my.github/x.yml",
        ".gitignore",
        ".claudeignore",
        "git/config",
        "claude/settings.json",
        "src/vscode/x.json",
        "README.md",
        "mcp.json",
        "src/.env.example",
        "docs/x.pth",
        ".venv/Lib/site-packages/x.py",
    ],
)
def test_an_ordinary_file_is_not_taken_for_one_that_gives_leave(tmp_path, path):
    assert not stands_over_later_turns(Workspace(tmp_path), path), path


def test_a_link_to_what_gives_leave_is_what_it_leads_to(tmp_path):
    project = tmp_path / "proj"
    (project / ".git" / "hooks").mkdir(parents=True)
    junction(project / "tools", project / ".git")
    try:
        ws = Workspace(project)
        assert stands_over_later_turns(ws, "tools/hooks/pre-commit")
        assert stands_over_later_turns(ws, "tools/config")
        assert not stands_over_later_turns(ws, "tool/config")
    finally:
        os.rmdir(project / "tools") if os.name == "nt" else (project / "tools").unlink()


def test_every_kind_of_file_that_is_not_written_unattended_says_why():
    for name, why in NOT_WRITTEN_UNATTENDED.items():
        assert name == name.casefold() and len(why) > 20, name
    assert set(NOT_WRITTEN_UNATTENDED) == {
        ".claude",
        ".codex",
        ".qoder",
        ".agy",
        ".agents",
        ".agent",
        "_agents",
        "_agent",
        ".git",
        ".github",
        ".vscode",
        ".husky",
        ".mcp.json",
        ".claude.json",
        "agents.md",
        "claude.md",
        "gemini.md",
        ".koloni",
        ".gemini",
        ".copilot",
        ".pre-commit-config.yaml",
        "lefthook.yml",
        "lefthook.yaml",
        ".lintstagedrc",
        ".lintstagedrc.json",
        ".lintstagedrc.yaml",
        ".lintstagedrc.yml",
        ".lintstagedrc.js",
        ".lintstagedrc.cjs",
        ".lintstagedrc.mjs",
        ".lefthook.yml",
        ".lefthook.yaml",
        "lefthook-local.yml",
        *(f"lint-staged.config.{ext}" for ext in ("js", "cjs", "mjs", "ts", "mts", "cts")),
        *(
            f"{dot}simple-git-hooks.{ext}"
            for dot in ("", ".")
            for ext in ("json", "js", "cjs", "mjs")
        ),
    }


@pytest.mark.parametrize("level", ["ask", "auto_edit", "full_auto"])
def test_a_turn_the_user_started_writes_such_files_on_their_word_at_every_level(
    make_client, wait_run, project_dir, level
):
    """With the user there such a file is put forward as a change to approve - at Full
    auto too (K-claude-yazma) - and written on their yes. (K-fullauto-sorma 2: at Full auto
    the instruction file alone is written unasked; `.claude` is a card there too.)"""
    client, model, pid, cid = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                step(call("write_file", {"path": ".claude/settings.json", "content": "{}"}, "w")),
                step(call("write_file", {"path": "AGENTS.md", "content": "Be kind.\n"}, "a")),
                text("done"),
            ]
        },
        permission_mode=level,
        lead_hands_code=False,
    )  # (slice 48 off)
    run_id = client.post(
        f"/api/conversations/{cid}/messages", json={"content": "set it up"}
    ).json()["run"]["id"]
    for _ in range(1 if level == "full_auto" else 2):
        change = until(
            lambda: [
                c
                for c in client.get(f"/api/conversations/{cid}").json()["file_changes"]
                if c["status"] == "proposed"
            ],
            "a change is put forward",
        )[0]
        assert client.post(f"/api/file-changes/{change['id']}/approve").status_code == 200
    snap = wait_run(client, cid, run_id)
    assert [(t["name"], t["status"]) for t in snap["tool_calls"]] == [
        ("write_file", "succeeded"),
        ("write_file", "succeeded"),
    ]
    assert (project_dir / ".claude" / "settings.json").read_text(encoding="utf-8") == "{}"
    assert (project_dir / "AGENTS.md").read_text(encoding="utf-8") == "Be kind.\n"


# --- a conversation's allow list ------------------------------------------------------------


def test_a_command_is_put_on_a_conversations_allow_list_by_hand(make_client, project_dir):
    client, model, pid, cid = setup(make_client, project_dir, {"Lead": []})
    made = client.post(
        f"/api/conversations/{cid}/allowed-commands", json={"prefix": "  python   -m  pytest -q "}
    )
    assert made.status_code == 201, made.text
    assert made.json()["prefix"] == "python -m pytest -q"  # tidied, and whole: not cut
    # the same rule again is the rule that is there
    again = client.post(
        f"/api/conversations/{cid}/allowed-commands", json={"prefix": "python -m pytest  -q"}
    )
    assert again.status_code == 200 and again.json()["id"] == made.json()["id"]
    for bad in (
        "",
        "   ",
        "python hello.py && echo x",
        "python hello.py | more",
        "echo $HOME",
        "python hello.py > out.txt",
        "python hello.py\necho x",
        "env python hello.py",
        "FOO=1 python hello.py",
        "timeout 5 python hello.py",
        "cmd /c dir",
        "powershell -File x.ps1",
        "bash run.sh",
        "python " + "a" * 200,
    ):
        refused = client.post(f"/api/conversations/{cid}/allowed-commands", json={"prefix": bad})
        assert refused.status_code == 422, (bad, refused.text)
    assert (
        client.post(
            "/api/conversations/no-such/allowed-commands", json={"prefix": "git status"}
        ).status_code
        == 404
    )
    snap = client.get(f"/api/conversations/{cid}").json()
    assert [rule["prefix"] for rule in snap["allowed_commands"]] == ["python -m pytest -q"]
    # only from the app's own page: a request that does not say where it is from is not
    # the user's
    del client.headers["Origin"]
    assert (
        client.post(
            f"/api/conversations/{cid}/allowed-commands", json={"prefix": "git status"}
        ).status_code
        == 403
    )


def test_with_the_user_there_a_rule_still_covers_the_command_with_more_arguments(
    make_client, wait_run, project_dir
):
    """What a ticked rule means where nobody is watching changes nothing for a turn the
    user started: there it is the prefix it always was."""
    executor = ScriptedExecutor([Script(chunks=["hi\n"])])
    client, model, pid, cid = setup(
        make_client,
        project_dir,
        {
            "Lead": [
                step(call("run_command", {"command": "python hello.py --more"}, "c")),
                text("ran"),
            ]
        },
        executor=executor,
        permission_mode="ask",
    )
    allow(client, cid, "python hello.py")
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "run it"}).json()[
        "run"
    ]["id"]
    snap = wait_run(client, cid, run_id)
    assert [(c["command"], c["status"]) for c in snap["commands"]] == [
        ("python hello.py --more", "exited")
    ]


def test_a_command_is_put_on_a_conversations_list_only_from_the_apps_own_page(
    make_client, project_dir
):
    client, model, pid, cid = setup(make_client, project_dir, {"Lead": []})
    assert allow(client, cid, "  python   hello.py ")  # tidied like "Always run" does
    rules = client.get(f"/api/conversations/{cid}").json()["allowed_commands"]
    assert [r["prefix"] for r in rules] == ["python hello.py"]
    for bad in ("", "python hello.py && echo x", "x" * 300):
        assert (
            client.post(
                f"/api/conversations/{cid}/allowed-commands", json={"prefix": bad}
            ).status_code
            == 422
        ), bad
    del client.headers["Origin"]
    assert (
        client.post(
            f"/api/conversations/{cid}/allowed-commands", json={"prefix": "git status"}
        ).status_code
        == 403
    )
