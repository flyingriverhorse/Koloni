"""K-bilgi 5, freshness: learning again reads only what changed - a site's listed page by its
sitemap lastmod or a conditional GET (304), a project's file by its time - keeps the rest as it was
read, writes only the changed slices' sections, and says how many pages changed. With nothing
changed, a learning nobody clicked for (the weekly one) asks no model.

No test touches the network: `app.web.raw` and `app.web.resolve` are stood in for.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta

from app import knowledge, web
from tests.test_experts_scenarios import SITE, asker, known

MD = "text/markdown"
SITEMAP = f"{SITE}/sitemap.xml"


class Server:
    """A site that answers its pages - each (text, ETag or None) - with a 304 to an
    If-None-Match of its ETag; every request and its headers."""

    def __init__(self, monkeypatch, pages: dict):
        self.pages = pages
        self.asked: list[tuple[str, dict]] = []

        async def raw(method, url, headers, body, ip):
            self.asked.append((url, dict(headers)))
            if url not in self.pages:
                return web.Raw(404, {"content-type": "text/plain"}, b"nothing here")
            text, tag = self.pages[url]
            if tag and headers.get("If-None-Match") == tag:
                return web.Raw(304, {"etag": tag}, b"")
            kind = "application/xml" if url.endswith(".xml") else MD
            return web.Raw(200, {"content-type": kind, **({"etag": tag} if tag else {})},
                           text.encode())

        monkeypatch.setattr(web, "raw", raw)
        monkeypatch.setattr(web, "resolve", lambda host: ["93.184.216.34"])

    def fetched(self, path: str) -> list[dict]:
        """The headers of each request for that page."""
        return [headers for url, headers in self.asked if url == f"{SITE}{path}"]


def learn(root, kept, extend=True, said="## What it offers\n- pay() takes a payment"):
    ask, asked = asker(said)

    async def run():
        knowledge.begin(str(root), kept)
        try:
            return await knowledge.learn(str(root), kept, ask, None, "Fake · fake-model",
                                         extend=extend)
        finally:
            knowledge.end(str(root), kept)

    return asyncio.run(run()), asked


def folder(root):
    return root / ".koloni" / "knowledge" / "pay"


def parts(root) -> dict[str, bytes]:
    return {one.name: one.read_bytes() for one in (folder(root) / "pages").iterdir()}


def listed(*paths):
    return ("".join(f"- [{one}](/pay/{one})\n" for one in paths), None)


def test_a_page_answered_304_is_kept_as_read_and_nothing_unchanged_asks_a_model(
    monkeypatch, project_dir
):
    site = Server(monkeypatch, {
        f"{SITE}/pay/llms.txt": listed("a", "b"),
        f"{SITE}/pay/a": ("Refunds: refund() undoes a payment.", 'W/"a1"'),
        # (No ETag: read again, and kept by its text being the same.)
        f"{SITE}/pay/b": ("Payouts: payout() sends money.", None),
    })
    kept = known()
    first, asked = learn(project_dir, kept)
    assert len(asked) == 1 and first["changed"] is None  # (a first learning: nothing to compare)
    a = next(one for one in first["pages"] if one["source"] == f"{SITE}/pay/a")
    assert a["etag"] == 'W/"a1"' and len(a["sha"]) == 16
    before = parts(project_dir)
    guide = (folder(project_dir) / "guide.md").read_bytes()
    site.asked.clear()

    # The weekly check (nobody clicked): conditional requests, no model.
    again, asked = learn(project_dir, kept, extend=False)
    assert site.fetched("/pay/a")[0]["If-None-Match"] == 'W/"a1"'
    assert "If-None-Match" not in site.fetched("/pay/b")[0]
    assert asked == [] and again["changed"] == 0
    assert parts(project_dir) == before
    assert (folder(project_dir) / "guide.md").read_bytes() == guide
    assert again["learned_at"] > first["learned_at"]
    stored = json.loads((folder(project_dir) / "learned.json").read_text(encoding="utf-8"))
    assert stored["changed"] == 0 and knowledge.stale(str(project_dir), kept) is None

    # A click writes the guide again from the same pages (a model chosen anew); still read
    # conditionally, and still none changed.
    clicked, asked = learn(project_dir, kept)
    assert len(asked) == 1 and clicked["changed"] == 0 and parts(project_dir) == before


def test_an_unchanged_sitemap_lastmod_is_not_fetched_a_moved_one_is(monkeypatch, project_dir):
    def sitemap(a_mod):
        return (f"<urlset><url><loc>{SITE}/pay/a</loc><lastmod>{a_mod}</lastmod></url>"
                f"<url><loc>{SITE}/pay/b</loc><lastmod>2026-10-01</lastmod></url></urlset>",
                None)

    site = Server(monkeypatch, {
        SITEMAP: sitemap("2026-10-01"),
        f"{SITE}/pay/a": ("Refunds: refund() undoes a payment.", None),
        f"{SITE}/pay/b": ("Payouts: payout() sends money.", None),
    })
    kept = known()
    learn(project_dir, kept)
    site.asked.clear()
    again, asked = learn(project_dir, kept, extend=False)
    assert site.fetched("/pay/a") == [] and site.fetched("/pay/b") == []
    assert again["changed"] == 0 and asked == []
    site.pages[SITEMAP] = sitemap("2026-11-02")
    site.pages[f"{SITE}/pay/a"] = ("Refunds: refund() undoes a payment in 5 days.", None)
    moved, asked = learn(project_dir, kept, extend=False)
    assert len(site.fetched("/pay/a")) == 1 and site.fetched("/pay/b") == []
    assert moved["changed"] == 1 and len(asked) == 1


def test_a_changed_page_is_read_again_and_only_its_slice_is_written_again(
    monkeypatch, project_dir
):
    # Each page a slice of its own (one more part of it would pass `MAX_GUIDE_INPUT`): two
    # sections and the map.
    size = 55_000
    site = Server(monkeypatch, {
        f"{SITE}/pay/llms.txt": listed("a", "b"),
        f"{SITE}/pay/a": ("a" * size, '"a1"'),
        f"{SITE}/pay/b": ("b" * size, '"b1"'),
    })
    kept = known()
    first, asked = learn(project_dir, kept)
    assert len(asked) == 3 and len(first["sections"]) == 2
    # (The same length: a page grown would move the cuts of the slices after it - `_slices`.)
    site.pages[f"{SITE}/pay/b"] = ("c" * size, '"b2"')
    again, asked = learn(project_dir, kept, extend=False)
    assert again["changed"] == 1
    # The section of the unchanged page is the one written before; the changed page's is
    # asked, then the map - nothing else.
    assert again["sections"][0] == first["sections"][0]
    assert again["sections"][1]["file"] != first["sections"][1]["file"]
    assert len(asked) == 2 and "c" * 100 in asked[0][1]["content"]
    assert "a" * 100 not in asked[0][1]["content"]
    b = next(one for one in again["pages"] if one["source"] == f"{SITE}/pay/b")
    assert b["etag"] == '"b2"'


def test_a_validator_a_server_could_smuggle_a_header_with_is_not_kept(monkeypatch, project_dir):
    Server(monkeypatch, {
        f"{SITE}/pay/llms.txt": listed("a"),
        f"{SITE}/pay/a": ("pay()", '"x"\r\nX-Evil: 1'),
    })
    record, _asked = learn(project_dir, known())
    (page,) = [one for one in record["pages"] if one["read"]]
    assert "etag" not in page


def test_a_folder_reads_again_only_the_file_that_changed_and_keeps_the_others_sections(
    monkeypatch, project_dir
):
    docs = project_dir / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("a" * 55_000, encoding="utf-8")
    (docs / "b.md").write_text("b" * 55_000, encoding="utf-8")
    kept = known("docs")
    first, asked = learn(project_dir, kept)
    assert len(asked) == 3 and first["changed"] is None
    read = []
    attached = knowledge.attachments.read

    def reading(data, name):
        read.append(name)
        return attached(data, name)

    monkeypatch.setattr(knowledge.attachments, "read", reading)
    (docs / "b.md").write_text("c" * 55_000, encoding="utf-8")
    assert knowledge.stale(str(project_dir), kept) == "docs/b.md changed since"
    again, asked = learn(project_dir, kept, extend=False)
    assert read == ["b.md"] and again["changed"] == 1
    assert again["sections"][0] == first["sections"][0] and len(asked) == 2
    assert knowledge.stale(str(project_dir), kept) is None
    # Nothing changed: nothing read, no model.
    read.clear()
    _same, asked = learn(project_dir, kept, extend=False)
    assert read == [] and asked == []


def test_a_weekly_site_is_old_after_a_week_and_its_check_spends_nothing_unchanged(
    monkeypatch, project_dir
):
    Server(monkeypatch, {
        f"{SITE}/pay/llms.txt": listed("a"),
        f"{SITE}/pay/a": ("Refunds: refund() undoes a payment.", '"a1"'),
    })
    kept = known(weekly=True)
    learn(project_dir, kept)
    path = folder(project_dir) / "learned.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["learned_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    path.write_text(json.dumps(record), encoding="utf-8")
    assert knowledge.stale(str(project_dir), kept) == knowledge.WEEKLY
    again, asked = learn(project_dir, kept, extend=False)
    assert asked == [] and again["changed"] == 0
    assert knowledge.stale(str(project_dir), kept) is None


def test_a_page_whose_address_is_cut_in_learned_json_is_never_given_anothers_text(
    monkeypatch, project_dir
):
    # Two addresses alike in their first 300 characters: learned.json keeps them cut to the
    # same words - a page of them is never kept as read, but read again.
    long = "x" * 300
    a, b = f"{SITE}/pay/{long}a", f"{SITE}/pay/{long}b"

    def sitemap(*urls):
        return ("<urlset>" + "".join(f"<url><loc>{one}</loc><lastmod>2026-10-01</lastmod></url>"
                                     for one in urls) + "</urlset>", None)

    site = Server(monkeypatch, {
        SITEMAP: sitemap(a),
        a: ("Refunds: refund() undoes a payment.", None),
        b: ("Payouts: payout() sends money.", None),
    })
    kept = known()
    learn(project_dir, kept)
    site.pages[SITEMAP] = sitemap(a, b)  # (b comes, with a's lastmod)
    site.asked.clear()
    learn(project_dir, kept, extend=False)
    assert len(site.fetched(f"/pay/{long}a")) == 1 and len(site.fetched(f"/pay/{long}b")) == 1
    texts = "".join(one.decode() for one in parts(project_dir).values())
    assert "refund()" in texts and "payout()" in texts


def test_a_lastmod_that_never_moves_is_asked_again_after_30_days(monkeypatch, project_dir):
    site = Server(monkeypatch, {
        SITEMAP: (f"<urlset><url><loc>{SITE}/pay/a</loc><lastmod>2026-01-01</lastmod></url>"
                  "</urlset>", None),
        f"{SITE}/pay/a": ("Refunds: refund() undoes a payment.", '"a1"'),
    })
    kept = known()
    learn(project_dir, kept)
    path = folder(project_dir) / "learned.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    (page,) = [one for one in record["pages"] if one["read"]]
    page["fetched"] = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    path.write_text(json.dumps(record), encoding="utf-8")
    site.asked.clear()
    again, asked = learn(project_dir, kept, extend=False)
    # Asked conditionally: a 304 keeps its text, and no model is asked.
    (headers,) = site.fetched("/pay/a")
    assert headers["If-None-Match"] == '"a1"' and asked == [] and again["changed"] == 0
    (page,) = [one for one in again["pages"] if one["read"]]
    assert datetime.now(UTC) - datetime.fromisoformat(page["fetched"]) < timedelta(minutes=5)
    # Fetched just now: trusted again, not asked.
    site.asked.clear()
    learn(project_dir, kept, extend=False)
    assert site.fetched("/pay/a") == []
