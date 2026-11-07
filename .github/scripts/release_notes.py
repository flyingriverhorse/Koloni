"""Release notes for the version in pyproject.toml, cut from CHANGELOG.md.

    python .github/scripts/release_notes.py [--tag vX.Y.Z] [--draft] > notes.md

Prints the version's section (`## [X.Y.Z] - date`, without the heading) and, in Actions, writes
`version=X.Y.Z` to $GITHUB_OUTPUT and points its relative links at the tag on GitHub.
Fails, so that no release goes out without notes:
- with --tag, unless the tag is v<pyproject version> (release.yml);
- with exit code 3 when the section is missing or empty. With --draft (release-drafter.yml, before
  the version is cut) the `## [Unreleased]` section stands in for a missing one.
A section ends at the next `# ` or `## ` heading outside a code fence, or at the reference-link
definitions (`[x]: https://...`) that close a changelog.
"""

import argparse
import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def section(changelog: str, name: str) -> str:
    """The body of `## [name]...`, without its heading; '' when there is none."""
    body: list[str] = []
    inside = fenced = False
    for line in changelog.replace("\r\n", "\n").split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced:
            ends = line.startswith(("# ", "## ")) or re.match(r"\[[^\]]+\]:\s", line)
            if inside and ends:
                break
            if line.startswith(f"## [{name}]"):
                inside = True
                continue
        if inside:
            body.append(line)
    return "\n".join(body).strip()


def absolute_links(notes: str, repo: str, tag: str) -> str:
    """Relative links pointed at the tag on GitHub; images, anchors and URLs left as they are."""
    return re.sub(r"(?<!!)(\[[^\]]*\])\((?![a-z]+:|#)",
                  lambda m: f"{m.group(1)}(https://github.com/{repo}/blob/{tag}/", notes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", help="the pushed tag; must be v<pyproject version>")
    parser.add_argument("--draft", action="store_true", help="fall back to [Unreleased]")
    args = parser.parse_args()

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    if args.tag is not None and args.tag != f"v{version}":
        print(f"error: tag {args.tag} is not v{version}, the version in pyproject.toml",
              file=sys.stderr)
        return 1
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = section(changelog, version) or (section(changelog, "Unreleased") if args.draft else "")
    if not notes:
        print(f"error: CHANGELOG.md has no '## [{version}] - YYYY-MM-DD' section with entries"
              + (" (nor an [Unreleased] one)" if args.draft else ""), file=sys.stderr)
        return 3
    if repo := os.environ.get("GITHUB_REPOSITORY"):
        # The changelog's links are relative to the repository; a release page needs them whole.
        notes = absolute_links(notes, repo, f"v{version}")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as out:
            out.write(f"version={version}\n")
    sys.stdout.reconfigure(encoding="utf-8")  # KOLONİ's İ on a Windows console
    print(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
