"""K-yabanci-talimat: another project's agent instruction files below the project's root -
which CLI agents load by themselves - are said on Project settings; the root's own are not."""

import os
import sys

from app import project_files


def _put(root, *paths):
    for rel in paths:
        target = root / rel
        if rel.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("follow me\n", encoding="utf-8")


def _found(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    answer = client.get(f"/api/projects/{pid}/others-instructions")
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_another_projects_instructions_are_said_and_the_roots_own_are_not(client, project_dir):
    _put(project_dir, "CLAUDE.md", "AGENTS.md", ".claude/settings.json",
         ".claude/skills/x/CLAUDE.md", ".github/copilot-instructions.md",
         "vendor/lib/CLAUDE.md", "sub/.claude/settings.json", "sub/.claude/skills/y/CLAUDE.md",
         "x/AGENTS.md", "y/.github/copilot-instructions.md", "y/.github/skills/s/SKILL.md",
         "y/.github/workflows/ci.yml", ".github/skills/mine/SKILL.md", "z/GEMINI.md",
         "w/.Codex/", "v/_agent/rules.md",
         "node_modules/pkg/CLAUDE.md", "node_modules/pkg/.claude/", ".git/modules/CLAUDE.md",
         ".venv/lib/AGENTS.md", "dist/AGENTS.md", "plain/readme.md")
    assert _found(client, project_dir) == {
        "paths": ["sub/.claude/", "v/_agent/", "w/.Codex/", "x/AGENTS.md", "z/GEMINI.md",
                  "vendor/lib/CLAUDE.md", "y/.github/copilot-instructions.md", "y/.github/skills/"],
        "more": 0, "partial": False,
    }


def test_a_link_is_not_followed(client, project_dir, tmp_path):
    outside = tmp_path / "elsewhere"
    _put(outside, "CLAUDE.md")
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(outside), str(project_dir / "door"))
    else:
        os.symlink(outside, project_dir / "door", target_is_directory=True)
    assert _found(client, project_dir)["paths"] == []


def test_too_deep_is_not_looked_in(project_dir, monkeypatch):
    monkeypatch.setattr(project_files, "MOST_DEEP", 2)
    _put(project_dir, "a/AGENTS.md", "a/b/AGENTS.md", "a/b/c/AGENTS.md")
    assert project_files.others_instructions(str(project_dir))["paths"] == [
        "a/AGENTS.md", "a/b/AGENTS.md"]


def test_many_are_counted_past_the_first_ten(project_dir):
    _put(project_dir, *(f"repo{n:02}/CLAUDE.md" for n in range(13)))
    found = project_files.others_instructions(str(project_dir))
    assert found["paths"] == [f"repo{n:02}/CLAUDE.md" for n in range(10)]
    assert found["more"] == 3 and not found["partial"]


def test_a_walk_cut_short_says_so(project_dir, monkeypatch):
    _put(project_dir, "a/AGENTS.md", "b/c/AGENTS.md")
    monkeypatch.setattr(project_files, "MOST_FOLDERS", 3)  # the root, a, b - not b/c
    assert project_files.others_instructions(str(project_dir)) == {
        "paths": ["a/AGENTS.md"], "more": 0, "partial": True}
    monkeypatch.setattr(project_files, "MOST_FOLDERS", 5000)
    monkeypatch.setattr(project_files, "MOST_SECONDS", -1.0)
    assert project_files.others_instructions(str(project_dir))["partial"]
