"""The release notes script (.github/scripts/release_notes.py): one version's changelog section."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "release_notes.py"
spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
assert spec and spec.loader
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)

CHANGELOG = """# Changelog

<!-- One version heading: `## [X.Y.Z] - YYYY-MM-DD` -->

## [Unreleased]

### Added

- **Chat**: next.

## [0.2.0] - 2026-12-01

### Fixed

- **Canvas**: a fix.

## [0.1.0] - 2026-11-20

### Added

- **Chat**: first.
"""


def test_a_versions_section_stops_at_the_next_version():
    assert release_notes.section(CHANGELOG, "0.2.0") == "### Fixed\n\n- **Canvas**: a fix."
    assert release_notes.section(CHANGELOG, "0.1.0") == "### Added\n\n- **Chat**: first."
    assert release_notes.section(CHANGELOG.replace("\n", "\r\n"), "Unreleased") == (
        "### Added\n\n- **Chat**: next.")


def test_a_missing_version_has_no_notes():
    assert release_notes.section(CHANGELOG, "0.3.0") == ""
    assert release_notes.section(CHANGELOG, "0.1") == ""
    assert release_notes.section("## [Unreleased]\n\n## [0.1.0] - 2026-11-20\n- x\n",
                                 "Unreleased") == ""


def test_a_section_stops_at_link_definitions_and_a_top_heading_but_not_inside_a_fence():
    text = ("## [0.1.0] - 2026-11-20\n\n- **Install**: run\n\n```text\n## not a heading\n```\n\n"
            "[0.1.0]: https://example.com/compare\n")
    assert release_notes.section(text, "0.1.0") == (
        "- **Install**: run\n\n```text\n## not a heading\n```")
    assert release_notes.section("## [0.1.0] - d\n- a\n# Older\n- b\n", "0.1.0") == "- a"


def test_relative_links_point_at_the_tag_and_images_stay():
    notes = "[docs](docs/a.md) [web](https://x.org) [here](#a) ![shot](docs/s.png)"
    assert release_notes.absolute_links(notes, "o/r", "v0.1.0") == (
        "[docs](https://github.com/o/r/blob/v0.1.0/docs/a.md) [web](https://x.org) [here](#a) "
        "![shot](docs/s.png)")


def test_only_a_dated_heading_is_release_ready():
    assert release_notes.dated(CHANGELOG, "0.2.0")
    assert release_notes.dated(CHANGELOG.replace("\n", "\r\n"), "0.1.0")
    assert not release_notes.dated(CHANGELOG, "Unreleased")
    assert not release_notes.dated(CHANGELOG, "0.3.0")
    assert not release_notes.dated("## [0.1.0]\n\n- x\n", "0.1.0")
    assert not release_notes.dated("## [0.1.0] - TBD\n\n- x\n", "0.1.0")
    assert not release_notes.dated("## [0.1.0.1] - 2026-11-20\n", "0.1.0")
