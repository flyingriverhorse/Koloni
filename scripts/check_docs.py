"""Checks the user guide (docs/) so it cannot go stale without a failing check.

  python scripts/check_docs.py             build the site with Zensical, then check
  python scripts/check_docs.py --no-build  check the site already in runtime/site

Fails (exit 1) on:
- a link in the built site to a page or #anchor that is not there (404.html is skipped);
- a link in README.md, SECURITY.md or CHANGELOG.md to a file that is not there;
- a file a diagram (docs/diagrams/*.drawio) names in its "From:" line that is gone, or a diagram
  with no such line (one saved compressed has none: save it uncompressed);
- a setting the guide's settings pages name that the app's Settings page does not show;
- a guide's Changelog page (docs/changelog.md) that is not CHANGELOG.md's: it is made from it,
  and written anew here before the build - commit it.

Labels match on exact text, ignoring case, with a typographic apostrophe read as a plain one.
An app label the guide never names is a warning only.
"""

from __future__ import annotations

import argparse
import glob
import html
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "runtime" / "site"
ROOT_DOCS = ("README.md", "SECURITY.md", "CHANGELOG.md")
GUIDE_SETTINGS = ("docs/settings.md", "docs/reference/all-settings.md")
# The Settings page and the section files it shows (This chat's rows are the chat's sheet, The app's
# Voice the voice controls').
APP_SETTINGS = (
    "frontend/src/shell/Settings.tsx",
    "frontend/src/shell/ProjectSettings.tsx",
    *sorted(str(p.relative_to(ROOT).as_posix())
            for p in (ROOT / "frontend/src/shell/sections").glob("*.tsx")),
    "frontend/src/chat/ChatSheet.tsx",
    "frontend/src/voice/VoiceControls.tsx",
    "frontend/src/shell/Backup.tsx",
    "frontend/src/shell/DeleteProject.tsx",
    "frontend/src/shell/Folders.tsx",
    "frontend/src/shell/OwnCommands.tsx",
    "frontend/src/shell/ProjectMap.tsx",
    "frontend/src/commands/ProjectRules.tsx",
    "frontend/src/commands/Sites.tsx",
)
# Bold names in those tables that are not settings on the Settings page.
NOT_SETTINGS = {
    "this chat": "a level's name (Three levels)",
    "this project": "a level's name (Three levels)",
    "the app": "a level's name (Three levels)",
    "tools": "a page of its own (all-settings.md, Other pages)",
    "knowledge": "a page of its own (all-settings.md, Other pages)",
    "triggers": "a page of its own (all-settings.md, Other pages)",
    "to-do": "a page of its own (all-settings.md, Other pages)",
    "usage": "a page of its own (all-settings.md, Other pages)",
}


def norm(text: str) -> str:
    return " ".join(text.replace("’", "'").split()).casefold()


# --- the built site ------------------------------------------------------------------------


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if value is None:
                continue
            if name == "id" or (tag == "a" and name == "name"):
                self.ids.add(value)
            elif (name == "href" and tag in ("a", "link")) or (name == "src" and tag == "img"):
                self.links.append(value)


def parse_page(text: str) -> tuple[set[str], list[str]]:
    """The ids a page has and the links it makes."""
    page = _Page()
    page.feed(text)
    return page.ids, page.links


def _target(site: Path, page: Path, path: str) -> Path:
    target = (page.parent / unquote(path)).resolve() if path else page
    if path.endswith("/") or target.is_dir():
        target = target / "index.html"
    return target


def broken_links(site: Path) -> list[str]:
    pages = {p.resolve(): parse_page(p.read_text(encoding="utf-8")) for p in site.rglob("*.html")}
    problems = []
    for page, (_, links) in pages.items():
        if page.name == "404.html" and page.parent == site.resolve():
            continue
        where = page.relative_to(site.resolve()).as_posix()
        for link in links:
            parts = urlsplit(link)
            if parts.scheme or link.startswith("//"):
                continue
            target = _target(site, page, parts.path)
            if not target.exists():
                problems.append(f"{where}: {link} (no such page)")
            elif parts.fragment and target.suffix == ".html":
                ids = pages[target][0] if target in pages else set()
                if unquote(parts.fragment) not in ids:
                    problems.append(f"{where}: {link} (no #{parts.fragment} there)")
    return problems


# --- README, SECURITY, CHANGELOG ----------------------------------------------------------

_MD_LINK = re.compile(r"\]\(([^)\s]+)|(?:src|href)=\"([^\"]+)\"")


def md_links(text: str) -> list[str]:
    """Local link targets in Markdown text, without their #anchor."""
    found = []
    for match in _MD_LINK.finditer(text):
        link = match.group(1) or match.group(2)
        parts = urlsplit(link)
        if parts.scheme or link.startswith(("//", "#")):
            continue
        found.append(unquote(parts.path))
    return found


# The guide's Changelog page, made from CHANGELOG.md (`changelog_page`); its other files' links go
# to the repository on GitHub.
CHANGELOG_PAGE = "docs/changelog.md"
REPOSITORY = "https://github.com/flyingriverhorse/Koloni/blob/main/"
# Inline code (left as it is), or a link to a file of the repository: its path, from the root
# with or without a leading slash, and its title if it has one - not a URL of any scheme, nor
# an anchor of the page.
_LOCAL_LINK = re.compile(
    r'(`+).*?\1|\]\((?![a-z][a-z0-9+.-]*:|#)/?([^)\s]+)(\s+"[^"]*")?\)', re.I | re.S)


def _linked(found: re.Match) -> str:
    if found[1]:
        return found[0]
    path = found[2]
    to = path.removeprefix("docs/") if path.startswith("docs/") else REPOSITORY + path
    return f"]({to}{found[3] or ''})"


def changelog_page(changelog: str) -> str:
    """CHANGELOG.md as the guide's page: without its comments, its links to docs/ pages the
    guide's own, any other file's the repository's."""
    text = _LOCAL_LINK.sub(_linked, re.sub(r"<!--.*?-->\n*", "", changelog, flags=re.S))
    return f"<!-- Made from CHANGELOG.md by scripts/check_docs.py: change that file. -->\n\n{text}"


def stale_changelog(root: Path) -> list[str]:
    """Writes the Changelog page anew where it is not CHANGELOG.md's: a problem until committed."""
    page, made = root / CHANGELOG_PAGE, changelog_page(
        (root / "CHANGELOG.md").read_text(encoding="utf-8"))
    if page.is_file() and page.read_text(encoding="utf-8") == made:
        return []
    page.write_text(made, encoding="utf-8", newline="\n")
    return [f"{CHANGELOG_PAGE} was not CHANGELOG.md's: written anew now, commit it"]


def missing_files(root: Path, names: tuple[str, ...]) -> list[str]:
    problems = []
    for name in names:
        doc = root / name
        for link in md_links(doc.read_text(encoding="utf-8")):
            if not (doc.parent / link).exists():
                problems.append(f"{name}: {link}")
    return problems


# --- diagrams ------------------------------------------------------------------------------

_FROM = re.compile(r"From:([^\"(<]*)")


def diagram_sources(text: str) -> list[str]:
    """The paths a .drawio file's "From:" line names (files, folders or globs)."""
    # The line sits in an escaped attribute, sometimes escaped twice and broken with <br>.
    text = html.unescape(html.unescape(text))
    text = re.sub(r"<br\s*/?>", " ", text)
    paths = []
    for match in _FROM.finditer(text):
        for token in re.split(r"[,\s]+", match.group(1)):
            token = token.strip("`'.;")
            if "/" in token or re.fullmatch(r"[\w.-]+\.\w+", token):
                paths.append(token)
    return paths


def stale_diagrams(root: Path) -> tuple[list[str], int]:
    problems = []
    drawings = sorted((root / "docs" / "diagrams").glob("*.drawio"))
    for drawing in drawings:
        sources = diagram_sources(drawing.read_text(encoding="utf-8"))
        if not sources:
            problems.append(f"{drawing.name}: no From: line")
        for source in sources:
            there = glob.glob(source, root_dir=root) if "*" in source else (root / source).exists()
            if not there:
                problems.append(f"{drawing.name}: {source}")
    return problems, len(drawings)


# --- settings names ------------------------------------------------------------------------

# Where the Settings page writes its labels: a Row or Field label, the text of a checkbox or
# radio button, a <label>, heading or legend, and the section list.
_APP_LABELS = (
    re.compile(r"(?<![\w-])label=\"([^\"]+)\""),
    re.compile(r"type=\"(?:checkbox|radio)\".*?/>\s*(?:\{' '\}\s*)?(?:<span>\s*)?([^<{]+)", re.S),
    re.compile(r"<(?:h2|h3|legend|label)\b[^>]*>([^<{]+)<"),
    re.compile(r"^\s*\['\w+', '([^']+)'\],?$", re.M),
)


def app_labels(source: str) -> set[str]:
    return {m.strip() for rx in _APP_LABELS for m in rx.findall(source) if m.strip()}


def guide_labels(markdown: str) -> list[str]:
    """The bold names in the first column of each table, and the names a "Section | Settings"
    table lists in its second column (separated by " · " or " / ")."""
    names = []
    listing = False
    for line in markdown.splitlines():
        if not line.startswith("|"):
            listing = False
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and set(cells[0]) <= set("-: "):
            continue
        if cells[:2] == ["Section", "Settings"]:
            listing = True
            continue
        names += re.findall(r"^\*\*(.+?)\*\*$", cells[0])
        if listing and len(cells) > 1:
            names += [n.strip() for n in re.split(r" · | / ", cells[1]) if n.strip()]
    return names


def label_problems(root: Path) -> tuple[list[str], list[str]]:
    app = {norm(label): label for name in APP_SETTINGS
           for label in app_labels((root / name).read_text(encoding="utf-8"))}
    guide = {}
    for name in GUIDE_SETTINGS:
        for label in guide_labels((root / name).read_text(encoding="utf-8")):
            guide.setdefault(norm(label), f"{name}: {label}")
    problems = [where for key, where in guide.items() if key not in app and key not in NOT_SETTINGS]
    text = norm("\n".join((root / name).read_text(encoding="utf-8") for name in GUIDE_SETTINGS))
    unmentioned = [label for key, label in app.items() if key not in text]
    return problems, sorted(unmentioned)


# --- main ----------------------------------------------------------------------------------


def build() -> None:
    # This Python's own Zensical first: verify.ps1 runs without the venv on PATH.
    zensical = shutil.which("zensical", path=str(Path(sys.executable).parent)) or "zensical"
    subprocess.run([zensical, "build"], cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-build", action="store_true", help="check runtime/site as it is")
    args = parser.parse_args()
    changelog = stale_changelog(ROOT)  # (before the build: the site shows it as it is now)
    if not args.no_build:
        build()
    if not (SITE / "index.html").exists():
        print(f"check_docs: no built site in {SITE}")
        return 1

    failed = False

    def report(title: str, problems: list[str]) -> None:
        nonlocal failed
        failed = failed or bool(problems)
        print(f"{title}: {'FAILED' if problems else 'ok'}")
        for problem in problems:
            print(f"  {problem}")

    report("links in the site", broken_links(SITE))
    report("links in README, SECURITY, CHANGELOG", missing_files(ROOT, ROOT_DOCS))
    report("the Changelog page", changelog)
    problems, count = stale_diagrams(ROOT)
    report(f"diagrams ({count})" if count else "diagrams (no diagrams)", problems)
    problems, unmentioned = label_problems(ROOT)
    report("settings named in the guide", problems)
    for label in unmentioned:
        print(f"  warning: the guide's settings pages never name {label!r}")
    print("check_docs: FAILED" if failed else "check_docs: OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
