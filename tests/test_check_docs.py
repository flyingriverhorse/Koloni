"""scripts/check_docs.py's parsing on small fixtures: links and anchors in a built site,
Markdown links, a diagram's "From:" line, and the settings labels on both sides."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "check_docs.py"
_spec = importlib.util.spec_from_file_location("check_docs", SCRIPT)
assert _spec and _spec.loader
docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(docs)


def test_parse_page_ids_and_links():
    ids, links = docs.parse_page(
        '<h2 id="saving">Saving</h2><a name="old"></a>'
        '<a href="../memory/#kinds">m</a><img src="a.png"><a>no href</a>'
    )
    assert ids == {"saving", "old"}
    assert links == ["../memory/#kinds", "a.png"]


def test_broken_links_finds_missing_page_and_anchor(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "index.html").write_text('<h2 id="kinds">K</h2>', encoding="utf-8")
    (tmp_path / "index.html").write_text(
        '<a href="memory/#kinds">ok</a><a href="memory/#gone">bad anchor</a>'
        '<a href="nowhere/">bad page</a><a href="https://example.com/x">outside</a>'
        '<a href="#top">self</a><p id="top"></p>',
        encoding="utf-8",
    )
    # 404.html links relative to wherever it is served: never checked.
    (tmp_path / "404.html").write_text('<a href="missing/">x</a>', encoding="utf-8")
    assert docs.broken_links(tmp_path) == [
        "index.html: memory/#gone (no #gone there)",
        "index.html: nowhere/ (no such page)",
    ]


def test_md_links_keeps_local_paths_only():
    text = (
        "[a](docs/index.md) [b](docs/use/ready.md#cards) [c](https://x.org) [d](#here)\n"
        '<img src="frontend/logo.png"> [e](docs/x.md "title") [f](mailto:a@b.c)'
    )
    assert docs.md_links(text) == [
        "docs/index.md",
        "docs/use/ready.md",
        "frontend/logo.png",
        "docs/x.md",
    ]


def test_diagram_sources_reads_escaped_from_line():
    text = (
        '<mxCell value="From: app/main.py, app/api/, app/model_*.py,&amp;lt;br&amp;gt;'
        'app/triggers.py&#xa;pyproject.toml (6 Nov 2026)" />'
    )
    assert docs.diagram_sources(text) == [
        "app/main.py",
        "app/api/",
        "app/model_*.py",
        "app/triggers.py",
        "pyproject.toml",
    ]


def test_stale_diagrams(tmp_path):
    assert docs.stale_diagrams(tmp_path) == ([], 0)
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "model_tiers.py").write_text("", encoding="utf-8")
    (tmp_path / "docs" / "diagrams").mkdir(parents=True)
    (tmp_path / "docs" / "diagrams" / "map.drawio").write_text(
        '<mxCell value="From: app/, app/model_*.py, app/gone.py (6 Nov 2026)" />', encoding="utf-8"
    )
    assert docs.stale_diagrams(tmp_path) == (["map.drawio: app/gone.py"], 1)


def test_app_labels():
    source = """
export const SECTIONS: [Section, string][] = [
  ['agents', 'Agents'],
  ['web', 'Web search'],
]
      <Row label="Who changes the files" htmlFor="lead-work">
      <input aria-label="Not a label" />
      <label className="choice">
        <input type="checkbox" checked={a} onChange={e => set(e.target.checked)} />
        <span>
          Finish only when the tests pass
          <span className="choice-note">note</span>
        </span>
      </label>
      <input type="radio" name="w" onChange={() => set('merge')} /> Merge here
      <legend>How a team’s finished branch reaches yours</legend>
      <label htmlFor="own-name">Name</label>
      <h2>Money</h2>
"""
    assert docs.app_labels(source) == {
        "Agents",
        "Web search",
        "Who changes the files",
        "Finish only when the tests pass",
        "Merge here",
        "How a team’s finished branch reaches yours",
        "Name",
        "Money",
    }


def test_guide_labels_and_norm():
    markdown = """
| Setting | What it does |
|---|---|
| **When you're away** | **Everything waits for you**, or more. |
| plain row | not bold |

| Section | Settings |
|---|---|
| **Rooms** | Posts, at most · Tokens, at most |
| **Commands** | This machine / Docker container |

| Page | Settings |
|---|---|
| **Usage** | Prices · not a list here |
"""
    assert docs.guide_labels(markdown) == [
        "When you're away",
        "Rooms",
        "Posts, at most",
        "Tokens, at most",
        "Commands",
        "This machine",
        "Docker container",
        "Usage",
    ]
    assert docs.norm("When  you’re Away") == docs.norm("when you're away")


def test_changelog_page_links_the_guides_pages_and_the_repositorys_files():
    made = docs.changelog_page(
        "# Changelog\n\n<!--\nhow to write\n-->\n\n## [0.1.0]\n\n- **Chat**: talk ([docs](docs/use/"
        "ready.md#cards)); AGPL ([docs](LICENSE)), [site](https://x.dev/a.md), [top](#changelog)\n")
    assert made.endswith(
        "# Changelog\n\n## [0.1.0]\n\n- **Chat**: talk ([docs](use/ready.md#cards)); AGPL ([docs]("
        f"{docs.REPOSITORY}LICENSE)), [site](https://x.dev/a.md), [top](#changelog)\n")
    assert "how to write" not in made


def test_changelog_page_reads_titles_root_paths_any_scheme_and_leaves_code_alone(tmp_path):
    made = docs.changelog_page('[a](/docs/use/ready.md "Ready") [b](/SECURITY.md) '
                               "[c](HTTPS://x.dev/y) `[d](docs/x.md)` [e](mailto:me@x.dev)")
    assert made.endswith(f'[a](use/ready.md "Ready") [b]({docs.REPOSITORY}SECURITY.md) '
                         "[c](HTTPS://x.dev/y) `[d](docs/x.md)` [e](mailto:me@x.dev)")
    # no page yet: written, and said once
    (tmp_path / "docs").mkdir()
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    assert docs.stale_changelog(tmp_path) and docs.stale_changelog(tmp_path) == []
