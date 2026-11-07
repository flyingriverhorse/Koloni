"""K-uzman, part 1's review round, what is read: on its site and under its path, within its
tries and its time; the topic a folder's name; the guide asked once, capped, paid for before
anything is read; a folder read whole old once a file comes or goes; the pages out of git; an
expert reads and talks only. Contract: `tests/test_experts_scenarios.py`.
"""

import asyncio
import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app import knowledge, web
from tests.test_chat_teams_scenarios import OWN
from tests.test_experts_scenarios import (
    EXPERT,
    MD,
    OPEN,
    READS,
    SITE,
    Site,
    known,
    learn,
    read,
    skipped,
)
from tests.test_knowledge_page import expert

# --- what is read ---------------------------------------------------------------------------


def test_a_sitemap_robots_txt_names_on_another_site_is_never_asked(monkeypatch, project_dir):
    site = Site(monkeypatch, {
        f"{SITE}/robots.txt": (200, "text/plain", "Sitemap: https://evil.test/s.xml?x=1\n"),
        f"{SITE}/sitemap.xml": (200, "application/xml", f"<loc>{SITE}/pay/a</loc>"),
        f"{SITE}/pay/a": (200, MD, "pay()"),
    })
    record, _asked = learn(project_dir, known())
    assert read(record) == [f"{SITE}/pay/a"]
    assert not any("evil.test" in one for one in site.asked)


def test_a_link_that_climbs_out_of_the_path_is_not_asked(monkeypatch, project_dir):
    site = Site(monkeypatch, {
        f"{SITE}/robots.txt": OPEN,
        f"{SITE}/pay/llms.txt": (200, "text/plain", (
            f"- [a]({SITE}/pay/../admin/secret)\n- [b](/pay/%2e%2e/admin2)\n- [c](/pay/c)\n")),
        f"{SITE}/pay/c": (200, MD, "pay()"),
    })
    record, _asked = learn(project_dir, known())
    assert read(record) == [f"{SITE}/pay/c"]
    assert set(skipped(record).values()) == {"outside /pay"}
    assert not any("admin" in one for one in site.asked)


def test_a_learning_tries_three_times_its_page_limit_at_most_and_says_only_its_sources(
    monkeypatch, project_dir
):
    links = "".join(f"- [p](/pay/{n})\n" for n in range(1000))
    site = Site(monkeypatch, {f"{SITE}/robots.txt": OPEN,
                              f"{SITE}/pay/llms.txt": (200, "text/plain", links)})
    with pytest.raises(knowledge.LearnError) as said:
        learn(project_dir, known(max_pages=5))
    assert len([one for one in site.asked if one.startswith(f"{SITE}/pay/") and
                not one.endswith(".txt")]) == 15
    # (Nothing a server chose is said outside the frame: the user's own source, and a count.)
    assert str(said.value) == f"nothing could be read of {SITE}/pay (15 tried)"


def test_a_learning_reads_for_ten_minutes_at_most(monkeypatch, project_dir):
    async def slow(method, url, headers, body, ip):
        await asyncio.sleep(1)
        return web.Raw(404, {}, b"")

    monkeypatch.setattr(web, "raw", slow)
    monkeypatch.setattr(web, "resolve", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(knowledge, "READING_SECONDS", 0.2)
    with pytest.raises(knowledge.LearnError, match="reading its sources took more than"):
        learn(project_dir, known())


def test_the_whole_sites_llms_full_txt_is_not_read_for_a_path_of_it(monkeypatch, project_dir):
    site = Site(monkeypatch, {
        f"{SITE}/robots.txt": OPEN,
        f"{SITE}/llms-full.txt": (200, "text/plain", "everything of the site"),
        f"{SITE}/sitemap.xml": (200, "application/xml", f"<loc>{SITE}/pay/a</loc>"),
        f"{SITE}/pay/a": (200, MD, "pay()"),
    })
    record, _asked = learn(project_dir, known())
    assert read(record) == [f"{SITE}/pay/a"] and f"{SITE}/llms-full.txt" not in site.asked


@pytest.mark.parametrize(("url", "path"), [
    ("https://github.com/some.user", "/some.user"), ("https://docs.test/docs/v1.2", "/docs/v1.2"),
    ("https://docs.test/docs/index.html", "/docs"), ("https://docs.test/pay/", "/pay")])
def test_only_a_pages_own_name_is_left_off_the_path(url, path):
    assert knowledge._scope(url)[1] == path


@pytest.mark.parametrize("topic", ["CON", "nul", "lpt1"])
def test_a_topic_is_no_name_windows_keeps_for_a_device(topic):
    with pytest.raises(ValueError, match="device"):
        known(topic=topic)


def test_the_guide_is_asked_once_capped_and_only_once_the_money_limit_pays(
    monkeypatch, project_dir
):
    site = Site(monkeypatch, {f"{SITE}/robots.txt": OPEN})
    price = SimpleNamespace(input=3.0, output=15.0, currency="USD")
    with pytest.raises(knowledge.LearnError, match="money limit"):
        learn(project_dir, known(max_usd=0.01), price=price)
    assert site.asked == []  # (a limit that pays for no guide reads nothing)
    (project_dir / "api.md").write_text("pay()", encoding="utf-8")
    _record, asked = learn(project_dir, known("api.md"))
    assert asked[0][0]["content"].startswith("You are asked one thing: to write a short guide")
    assert "You are asked one thing" not in asked[0][1]["content"]

    class Takes:
        async def stream_step(self, model_id, messages, tools, on_delta, max_tokens=None):
            pass

    class Not:
        async def stream_step(self, model_id, messages, tools, on_delta):
            pass

    assert knowledge.most_written(Takes()) == {"max_tokens": knowledge.GUIDE_TOKENS}
    assert knowledge.most_written(Not()) == {}


def test_a_folder_read_whole_is_old_once_a_file_comes_or_goes_and_its_pages_stay_out_of_git(
    project_dir
):
    (project_dir / "docs").mkdir()
    (project_dir / "docs" / "a.md").write_text("a()", encoding="utf-8")
    kept = known("docs")
    learn(project_dir, kept)
    folder = project_dir / ".koloni" / "knowledge" / "pay"
    assert "pages/" in (folder / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert knowledge.stale(str(project_dir), kept) is None
    (project_dir / "docs" / "b.md").write_text("b()", encoding="utf-8")
    assert knowledge.stale(str(project_dir), kept) == "docs/b.md was added since"
    (project_dir / "docs" / "b.md").unlink()
    (project_dir / "docs" / "a.md").unlink()
    assert knowledge.stale(str(project_dir), kept) == "docs/a.md is gone since"


def test_an_expert_holds_reading_and_talking_only(client, project_dir):
    kid = expert(client, project_dir, EXPERT)["knowledge_id"]
    for more in ("http_request", "spawn_agent", "create_role", "notify"):
        role = client.post("/api/roles", headers=OWN, json={
            **{k: v for k, v in EXPERT.items() if k != "knowledge"}, "name": f"With {more}",
            "tools": [*READS, more]}).json()
        refused = client.put(f"/api/knowledge/{kid}/roles/{role['id']}", json={"mode": "full"},
                             headers=OWN)
        assert refused.status_code == 422 and more in refused.text, more


def test_a_file_is_old_by_its_own_time_as_it_was_read_not_by_the_learnings_start(project_dir):
    (project_dir / "api.md").write_text("pay()", encoding="utf-8")
    kept = known("api.md")
    learn(project_dir, kept)
    record = knowledge.learned(str(project_dir), kept)
    stamp = record["pages"][0]["mtime_ns"]
    # Its time landed a tick after the clock was read: as it was read, it is no change.
    later = datetime.fromisoformat(record["learned_at"]).timestamp() + 1
    os.utime(project_dir / "api.md", ns=(stamp, stamp))
    record["learned_at"] = datetime.fromtimestamp(later - 2, UTC).isoformat()
    (project_dir / ".koloni" / "knowledge" / "pay" / "learned.json").write_text(
        json.dumps(record), encoding="utf-8")
    assert knowledge.stale(str(project_dir), kept) is None
    os.utime(project_dir / "api.md", ns=(stamp + 10**9, stamp + 10**9))
    assert knowledge.stale(str(project_dir), kept) == "api.md changed since"
    # A record from before the times were kept: by the learning's start, as it was.
    del record["pages"][0]["mtime_ns"]
    (project_dir / ".koloni" / "knowledge" / "pay" / "learned.json").write_text(
        json.dumps(record), encoding="utf-8")
    assert knowledge.stale(str(project_dir), kept) == "api.md changed since"
