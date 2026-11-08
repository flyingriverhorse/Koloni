"""Slice 45, design 9: a skill from a public GitHub repository. Its listing is read first and
shown; the rest is downloaded on the user's yes, from the very commit that was listed, each
file checked against the listing. Nothing here reaches GitHub: `skill_github.fetch` is the
one way out, and every test puts its own in its place."""

import json

import pytest

from app import skill_github, skills
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_skill_scenarios import ORIGIN, SKILL_MD
from tests.test_spawn import begin, call, step

SHA = "a" * 40
API = "https://api.github.com/repos/acme/kit"
RAW = f"https://raw.githubusercontent.com/acme/kit/{SHA}/"
ADDRESS = "https://github.com/acme/kit/tree/main/skills/tidy"
FILES = {
    "LICENSE": b"MIT License\n",
    "skills/tidy/SKILL.md": SKILL_MD.encode(),
    "skills/tidy/scripts/check.py": b"print('ok')\n",
    "skills/tidy/notes.md": b"NOTES",
    "skills/tidy/.env": b"TOKEN=1",
    "other/SKILL.md": b"not this one",
}


def entry(path, data=b"", mode="100644", kind="blob"):
    return {"path": path, "mode": mode, "type": kind, "sha": skills.blob_id(data),
            "size": len(data)}


class Repo:
    """GitHub as the tests have it: the addresses asked for, and what each answers."""

    def __init__(self, files=FILES, extra=(), truncated=False):
        tree = [entry(path, data) for path, data in files.items()]
        tree += [entry("skills/tidy/link", mode="120000"),
                 entry("skills/tidy/vendor", mode="160000", kind="commit"), *extra]
        self.answers = {
            API: json.dumps({"default_branch": "main"}).encode(),
            f"{API}/commits/main": json.dumps({"sha": SHA}).encode(),
            f"{API}/git/trees/{SHA}?recursive=1": json.dumps(
                {"tree": tree, "truncated": truncated}).encode(),
            **{RAW + path: data for path, data in files.items()},
        }
        self.asked: list[str] = []

    def fetch(self, url, limit):
        self.asked.append(url)
        data = self.answers[url]
        if len(data) > limit:
            raise skills.SkillError("larger than listed")
        return data

    def raw(self):
        return [url.removeprefix(RAW) for url in self.asked if url.startswith(RAW)]


@pytest.fixture
def repo(monkeypatch):
    made = Repo()
    monkeypatch.setattr(skill_github, "fetch", made.fetch)
    return made


def test_the_listing_is_read_from_one_commit_and_nothing_else_is_downloaded(repo):
    found = skill_github.listing(ADDRESS)
    assert sorted(found.files) == ["SKILL.md", "notes.md", "scripts/check.py"]
    assert found.source == f"{ADDRESS}@{SHA}"
    assert found.license == "MIT License"  # the repository's, the folder having none
    assert {".env", "link", "vendor"} <= set(found.shown()["skipped"])
    assert found.shown()["script_texts"] == {"scripts/check.py": "print('ok')\n"}
    assert sorted(repo.raw()) == ["LICENSE", "skills/tidy/SKILL.md", "skills/tidy/scripts/check.py"]
    whole = skills.whole(found)
    assert whole.contents["notes.md"] == b"NOTES"
    assert "skills/tidy/notes.md" in repo.raw()


def test_a_pinned_address_is_not_resolved_again(repo):
    found = skill_github.listing(f"{ADDRESS}@{SHA}")
    assert found.source == f"{ADDRESS}@{SHA}"
    assert f"{API}/commits/main" not in repo.asked


def test_a_file_that_is_not_what_was_listed_is_refused(repo):
    found = skill_github.listing(ADDRESS)
    repo.answers[RAW + "skills/tidy/notes.md"] = b"N0TES"  # as long, not the same
    with pytest.raises(skills.SkillError, match="not what was listed"):
        skills.whole(found)


@pytest.mark.parametrize("path", [
    "skills/tidy/../evil", "skills/tidy/con.txt", "skills/tidy/a:b", "skills/tidy/NOTES.md",
    "skills/tidy/x\\y", "skills/tidy/CONIN$", "skills/tidy/com¹.txt", "skills/tidy/nul .txt",
    # (an 8.3 short name, a name NTFS will not hold, one file under NTFS's case: "I" for "ı")
    "skills/tidy/LONGRE~1.MD", "skills/tidy/" + "a" * 256, "skills/tidy/SKıLL.md",
])
def test_a_path_no_file_here_may_have_is_refused(monkeypatch, path):
    monkeypatch.setattr(skill_github, "fetch", Repo(extra=[entry(path, b"x")]).fetch)
    with pytest.raises(skills.SkillError):
        skill_github.listing(ADDRESS)


def test_the_caps_hold_on_the_listing_before_any_download(monkeypatch):
    big = Repo(extra=[{**entry("skills/tidy/big.bin"), "size": skills.MAX_BYTES}])
    monkeypatch.setattr(skill_github, "fetch", big.fetch)
    with pytest.raises(skills.SkillError, match="at most 5 MiB"):
        skill_github.listing(ADDRESS)
    assert big.raw() == []
    cut = Repo(truncated=True)
    monkeypatch.setattr(skill_github, "fetch", cut.fetch)
    with pytest.raises(skills.SkillError, match="too large"):
        skill_github.listing(ADDRESS)


def test_only_github_is_reached_and_its_refusals_are_said_plainly():
    with pytest.raises(skills.SkillError, match="GitHub"):
        skill_github.fetch("https://example.com/x", 10)  # refused before any request
    with pytest.raises(skills.SkillError, match="GitHub"):
        skill_github.fetch("http://api.github.com/x", 10)
    assert "60 an hour" in skill_github.refusal(403, {"x-ratelimit-remaining": "0"})
    assert "60 an hour" in skill_github.refusal(429, {})
    assert "public" in skill_github.refusal(404, {})
    for bad in ("github.com/acme", "https://gitlab.com/a/b", "https://github.com/a/b/blob/x"):
        with pytest.raises(skills.SkillError, match="GitHub address"):
            skill_github.listing(bad)


def test_the_user_adds_one_from_github_after_seeing_its_listing(make_client, repo):
    client, _model = make_client([])
    shown = client.post("/api/skills/preview", json={"github": ADDRESS}, headers=ORIGIN)
    assert shown.status_code == 200, shown.text
    assert client.get("/api/skills").json() == []
    assert "skills/tidy/notes.md" not in repo.raw()
    made = client.post("/api/skills", json={
        "github": shown.json()["source"], "sha256": shown.json()["sha256"]}, headers=ORIGIN)
    assert made.status_code == 201, made.text
    assert made.json()["source"] == f"{ADDRESS}@{SHA}"
    assert sorted(made.json()["files"]) == ["SKILL.md", "notes.md", "scripts/check.py"]


def test_the_lead_proposes_one_from_github_and_it_is_downloaded_on_the_yes(
    make_client, wait_run, project_dir, repo
):
    client, _model = make_client([
        step(call("add_skill", {"github": ADDRESS, "roles": ["Coder"]}, "k1")), text("added")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    (card,) = wait_status(client, cid, "waiting_approval")["pending_skills"]
    assert card["source"] == f"{ADDRESS}@{SHA}" and card["license"] == "MIT License"
    assert "skills/tidy/notes.md" not in repo.raw()
    client.post(f"/api/tool-calls/{card['tool_call_id']}/approve", headers=ORIGIN)
    wait_run(client, cid, run_id)
    assert "skills/tidy/notes.md" in repo.raw()
    (kept,) = client.get("/api/skills").json()
    assert kept["name"] == "tidy"
