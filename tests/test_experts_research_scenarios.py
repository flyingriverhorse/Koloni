"""K-uzman, part 2: an expert that researches a topic ("research: <topic>").

Design: `tasarim/plans/is-dizini.md` (K-uzman, part 2).

Contract:
- A source can be only a topic: learning searches for it with the project's own search (the one
  its agents' web_search makes, without the paid API one) and reads each page found as a site is
  read from that page - only on its own site and under its own path, along its links, robots.txt
  obeyed, within the page limit and the tries.
- A found page is said as found: the user can take it off the list, and it is never read again.
- Searching is a network action: under the same leave as an address (an agent's expert needs an
  opener that searches; unwatched, the trigger has to allow searching, and only a site it names is
  read; a project with no network learns nothing from the web).

No test touches the network: the search and the pages are stood in for.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from app import knowledge, web
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN
from tests.test_experts_scenarios import (
    EXPERT,
    HTML,
    MD,
    OPEN,
    Site,
    asker,
    known,
    read,
    skipped,
    wait_learned,
)
from tests.test_experts_work_scenarios import offered_to
from tests.test_knowledge_page import expert
from tests.test_spawn import begin, call, spawn, step
from tests.test_trigger_scenarios import NOBODY, run_now, trigger
from tests.test_web_tool_scenarios import setup

A, B = "https://a.test", "https://b.test"
RESEARCH = "research: pay webhooks"


def searcher(*urls):
    asked: list[str] = []

    async def search(query):
        asked.append(query)
        return [{"title": url, "url": url, "snippet": ""} for url in urls]

    return search, asked


def learn(root, kept, search, may=lambda url: None):
    ask, asked = asker()

    async def run():
        knowledge.begin(str(root), kept)
        try:
            return await knowledge.learn(str(root), kept, ask, None, "Fake · fake", search, may)
        finally:
            knowledge.end(str(root), kept)

    return asyncio.run(run()), asked


PAGES = {
    f"{A}/robots.txt": OPEN,
    f"{A}/docs/hooks": (200, HTML, "<p>constructEvent checks a webhook</p>"
                                   "<a href='/docs/hooks/retry'>retry</a><a href='/blog'>b</a>"),
    f"{A}/docs/hooks/retry": (200, MD, "Webhooks are retried for 3 days."),
    f"{A}/blog": (200, MD, "beside the path"),
    f"{A}/docs/llms.txt": (200, "text/plain", "- [x](/docs/x)\n"),
    f"{B}/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /forum\n"),
    f"{B}/forum/t/1": (200, MD, "someone says so"),
}


def test_a_topic_is_searched_for_and_each_page_found_read_only_under_its_own_path(
    monkeypatch, project_dir
):
    site = Site(monkeypatch, PAGES)
    search, queries = searcher(f"{A}/docs/hooks#top", f"{B}/forum/t/1", f"{A}/docs/hooks")

    record, asked = learn(project_dir, known(RESEARCH), search)

    assert queries == ["pay webhooks"]
    # Its links under its path are followed; the site's own lists are not read for one page.
    assert read(record) == [f"{A}/docs/hooks", f"{A}/docs/hooks/retry"]
    assert skipped(record) == {f"{B}/forum/t/1": "robots.txt asks not to"}
    assert not {f"{A}/blog", f"{A}/docs/llms.txt", f"{B}/forum/t/1"} & set(site.asked)
    assert all(one["found"] for one in record["pages"])
    assert "Webhooks are retried" in asked[0][1]["content"]
    # A topic is no file of the project: a guide just learned from it is not old.
    assert knowledge.stale(str(project_dir), known(RESEARCH)) is None


def test_a_page_taken_off_the_list_is_not_read_again(monkeypatch, project_dir):
    site = Site(monkeypatch, PAGES)
    search, _queries = searcher(f"{A}/docs/hooks")
    learn(project_dir, known(RESEARCH), search)
    kept = known(RESEARCH, removed=[f"{A}/docs/hooks/retry"])
    assert knowledge.stale(str(project_dir), kept) == "a page was removed from its sources since"
    site.asked.clear()

    record, _asked = learn(project_dir, kept, search)

    assert read(record) == [f"{A}/docs/hooks"]
    assert skipped(record) == {f"{A}/docs/hooks/retry": knowledge.REMOVED}
    assert f"{A}/docs/hooks/retry" not in site.asked
    # A found page itself taken off: not read, and none of its links either.
    (project_dir / "notes.md").write_text("pay()", encoding="utf-8")
    record, _asked = learn(project_dir, known(RESEARCH, "notes.md",
                                              removed=[f"{A}/docs/hooks"]), search)
    assert record["pages"][0] == {"source": f"{A}/docs/hooks", "read": False,
                                  "why": knowledge.REMOVED, "found": True}
    assert read(record) == ["notes.md"]


def test_a_search_that_fails_is_said(project_dir):
    async def down(query):
        raise web.WebError("search could not be made: DuckDuckGo did not answer (it asks to wait)")

    with pytest.raises(knowledge.LearnError, match="nothing could be read of research: pay"):
        learn(project_dir, known(RESEARCH), down)
    (project_dir / "notes.md").write_text("pay()", encoding="utf-8")
    record, _asked = learn(project_dir, known(RESEARCH, "notes.md"), down)
    assert skipped(record)[RESEARCH].endswith("(it asks to wait)")


@pytest.mark.parametrize("source", ["research:", "research:   ", "research: " + "x" * 301])
def test_a_topic_to_research_has_words_and_is_no_longer_than_a_query(source):
    with pytest.raises(ValueError, match="research: needs a topic"):
        known(source)


def test_a_topic_is_kept_as_its_words_are_evened_out():
    assert known("Research:  pay   webhooks ")["sources"] == [RESEARCH]


# --- under whose leave it searches ------------------------------------------------------------

RESEARCHER = {**EXPERT, "knowledge": {"topic": "Pay", "sources": [RESEARCH]}}


def test_only_an_opener_that_searches_gets_a_researcher_that_learns(
    make_client, wait_run, project_dir
):
    client, model = make_client({"Lead": [spawn("Pay expert", "learn", "e"), text("done")],
                                 "Pay expert": [text("I have not learned yet.")]})
    lead = next(r for r in client.get("/api/roles").json() if r["name"] == "Lead")
    assert client.patch(f"/api/roles/{lead['id']}", headers=OWN, json={
        "tools": [one for one in lead["tools"] if one != "web_search"]}).status_code == 200
    expert(client, project_dir, RESEARCHER)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="ask the Pay expert")
    wait_run(client, cid, run_id)
    assert "learn" not in offered_to(model, "Pay expert")


def test_an_agent_that_does_not_search_makes_no_researcher(make_client, wait_run, project_dir):
    made = call("create_role", {"name": "Hooks expert", "tools": ["read_file"],
                                "sources": ["research: stripe webhooks"]}, "r1")
    client, _model = make_client({"Lead": [step(made), text("could not")]})
    lead = next(r for r in client.get("/api/roles").json() if r["name"] == "Lead")
    assert client.patch(f"/api/roles/{lead['id']}", headers=OWN, json={
        "tools": [one for one in lead["tools"] if one != "web_search"]}).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto", content="make it")
    result = wait_run(client, cid, run_id)["tool_calls"][0]
    assert result["status"] == "failed" and "(web_search)" in result["result"]
    assert "makes none" in result["result"]


def fake_search(monkeypatch, *urls):
    asked: list[dict] = []

    async def results(query, search_url, order, spent=None, agy=False, paid=True):
        asked.append({"query": query, "paid": paid})
        return "Fake", [{"title": u, "url": u, "snippet": ""} for u in urls], ""

    monkeypatch.setattr(web, "results", results)
    return asked


def test_learn_on_the_tab_searches_with_the_projects_search_and_never_the_paid_one(
    make_client, project_dir, monkeypatch
):
    Site(monkeypatch, PAGES)
    searched = fake_search(monkeypatch, f"{A}/docs/hooks")
    client, _model = make_client({"Lead": [text("## What it offers\nWebhooks.")]})
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    role = expert(client, project_dir, RESEARCHER)
    assert client.post(f"/api/roles/{role['id']}/learn", json={"project_id": pid},
                       headers=OWN).status_code == 202
    state = wait_learned(client, role["id"], pid)
    assert state["failed"] is None, state["failed"]
    assert searched == [{"query": "pay webhooks", "paid": False}]
    assert [one["source"] for one in state["learned"]["pages"] if one["read"]] == [
        f"{A}/docs/hooks", f"{A}/docs/hooks/retry"]
    # The user takes a found page off its list: kept with its sources.
    removed = client.put(f"/api/knowledge/{role['knowledge_id']}", params={"project_id": pid},
                         headers=OWN, json={**role["knowledge"],
                                            "removed": [f"{A}/docs/hooks/retry#x"]})
    assert removed.status_code == 200, removed.text
    assert removed.json()["knowledge"]["removed"] == [f"{A}/docs/hooks/retry"]


def test_a_project_with_no_network_researches_nothing(make_client, project_dir, monkeypatch):
    searched = fake_search(monkeypatch, f"{A}/docs/hooks")
    client, _model = make_client({"Lead": [text("never")]})
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={
        "docker_image": "python:3.12", "exec_location": "docker"}).status_code == 200
    role = expert(client, project_dir, RESEARCHER)
    clicked = client.post(f"/api/roles/{role['id']}/learn", json={"project_id": pid}, headers=OWN)
    assert clicked.status_code == 409 and "network access is off" in clicked.text
    assert searched == []


def test_unwatched_it_researches_only_where_the_trigger_lets_it_search_and_names_the_site(
    make_client, wait_run, project_dir, monkeypatch
):
    site = Site(monkeypatch, PAGES)
    searched = fake_search(monkeypatch, f"{B}/forum/t/2", f"{A}/docs/hooks")
    client, _model, pid, cid = setup(make_client, project_dir, {
        "Lead": [spawn("Pay expert", "learn", "e"), text("done"),
                 spawn("Pay expert", "learn", "f"), text("## Hooks\nRetried."), text("done")],
        "Pay expert": [step(call("learn", {}, "l1")), text("could not"),
                       step(call("learn", {}, "l2")), text("learned")],
    })
    expert(client, project_dir, RESEARCHER)
    leave = {"write": True, "commands": [], "agents": 1}
    made = trigger(client, pid, cid, permissions=leave)
    snap = wait_run(client, cid, run_now(client, made["id"]), timeout=10)
    refused = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "l1")
    assert refused["status"] == "failed" and NOBODY in refused["result"]
    assert searched == []

    again = trigger(client, pid, cid, permissions={**leave, "web": True, "hosts": ["a.test"]})
    snap = wait_run(client, cid, run_now(client, again["id"]), timeout=10)
    learned = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "l2")
    assert learned["status"] == "succeeded", learned["result"]
    record = knowledge.learned(str(project_dir), known(RESEARCH))
    assert skipped(record) == {f"{B}/forum/t/2": "the trigger does not name this site"}
    assert f"{B}/forum/t/2" not in site.asked and read(record)[0] == f"{A}/docs/hooks"


# --- learned again weekly -------------------------------------------------------------------


def aged(root, days):
    path = root / ".koloni" / "knowledge" / "pay" / "learned.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["learned_at"] = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    path.write_text(json.dumps(record), encoding="utf-8")


def test_a_researched_guide_is_old_after_a_week_only_where_it_is_learned_weekly(
    monkeypatch, project_dir
):
    Site(monkeypatch, PAGES)
    search, _queries = searcher(f"{A}/docs/hooks")
    learn(project_dir, known(RESEARCH), search)
    root, weekly = str(project_dir), known(RESEARCH, weekly=True)
    assert knowledge.stale(root, weekly) is None
    aged(project_dir, 8)
    assert knowledge.stale(root, known(RESEARCH)) is None
    assert knowledge.stale(root, weekly) == knowledge.WEEKLY
    # At its own work it learns first; answering a message it only says so.
    assert "learn first (learn), then answer" in knowledge.brief(root, weekly, can_learn=True)
    assert "say so in your answer" in knowledge.brief(root, weekly)
    # Not for a guide of documents or files: they say when they change.
    (project_dir / "notes.md").write_text("pay()", encoding="utf-8")
    files = known("notes.md", weekly=True)
    learn(project_dir, files, search)
    aged(project_dir, 30)
    assert knowledge.stale(root, files) is None


def test_an_expert_at_work_learns_its_weekly_guide_first(make_client, wait_run, project_dir,
                                                       monkeypatch):
    Site(monkeypatch, PAGES)
    search, _queries = searcher(f"{A}/docs/hooks")
    learn(project_dir, known(RESEARCH, weekly=True), search)
    aged(project_dir, 8)
    client, model = make_client({"Lead": [spawn("Pay expert", "what retries?", "e"),
                                          text("done")],
                                 "Pay expert": [text("3 days.")]})
    expert(client, project_dir, {**RESEARCHER, "knowledge": {
        **RESEARCHER["knowledge"], "weekly": True}})
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="ask the Pay expert")
    wait_run(client, cid, run_id)
    assert "learn" in offered_to(model, "Pay expert")
    assert "learn first (learn), then answer" in model.calls_of["Pay expert"][0][0]["content"]


def test_a_long_address_taken_off_as_the_tab_shows_it_is_not_read_again(monkeypatch, project_dir):
    long = f"{A}/docs/hooks?" + "q=" + "x" * 350
    site = Site(monkeypatch, {f"{A}/robots.txt": OPEN, long: (200, MD, "a long one")})
    search, _queries = searcher(long)
    (project_dir / "notes.md").write_text("pay()", encoding="utf-8")
    record, _asked = learn(project_dir, known(RESEARCH, "notes.md"), search)
    shown = record["pages"][0]["source"]
    assert shown != long and shown.endswith("…")
    site.asked.clear()
    learn(project_dir, known(RESEARCH, "notes.md", removed=[shown]), search)
    assert long not in site.asked


def test_with_no_project_the_search_is_the_built_in_one(monkeypatch):
    asked = []

    async def results(query, search_url, order, spent=None, agy=False, paid=True):
        asked.append((search_url, order, agy, paid))
        return "Fake", [], ""

    monkeypatch.setattr(web, "results", results)
    asyncio.run(knowledge.searching(None)("pay"))
    assert asked == [(None, "builtin", False, False)]


def test_a_research_reads_pages_about_its_topic_in_no_other_language(monkeypatch, project_dir):
    # B-131 (live, research: tomli): under docs.python.org/pl/3.13/library/ it read configparser, netrc
    # and the index, and the Polish and Korean pages - "536 more not read".
    lib = f"{A}/3/library"
    Site(monkeypatch, {
        f"{A}/robots.txt": OPEN,
        f"{lib}/tomllib.html": (200, HTML, "<p>tomllib parses TOML</p><a href='netrc.html'>n</a>"
                                           f"<a href='{A}/pl/3/library/tomllib.html'>pl</a><a href='toml-howto.html'>t</a>"),
        f"{lib}/netrc.html": (200, HTML, "<p>netrc files</p><a href='configparser.html'>c</a>"),
        f"{lib}/toml-howto.html": (200, MD, "Read a TOML file with tomllib.load"),
        f"{lib}/configparser.html": (200, MD, "INI files"),
        f"{A}/pl/3/library/tomllib.html": (200, MD, "po polsku"),
    })
    search, _queries = searcher(f"{lib}/tomllib.html", f"{A}/ko/3/library/tomllib.html")
    record, _asked = learn(project_dir, known("research: toml parsing"), search)
    # The page its address names comes first; the one about none of it is read, its links not followed.
    assert read(record) == [f"{lib}/tomllib.html", f"{lib}/toml-howto.html", f"{lib}/netrc.html"]
    assert skipped(record) == {f"{A}/ko/3/library/tomllib.html": knowledge.LANGUAGE}
    assert record["unread"] == 0


def test_a_researchs_words_are_its_topics_in_turkish_too_without_the_little_ones():
    # (The review of B-131: Turkish letters split the words; "how", "the", "ile" told no page from another.)
    assert knowledge._words("how to parse TOML with tomllib", "https://docs.python.org/3/") == {
        "parse", "toml", "tomllib"}
    assert knowledge._words("şifre sıfırlama ile e-posta", "https://a.test/") == {"şifre", "sıfırlama", "posta"}
    assert not knowledge._other_language("https://a.test/ar/arrays")  # (no Arabic in the list: /ar/ is often a word)
