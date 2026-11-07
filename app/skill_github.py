"""A skill from a public GitHub repository (slice 45, design 9). Its listing is read first:
the files and their sizes, its SKILL.md, licence and scripts - the rest only on the user's
yes, from the very commit that was listed, each file checked against the listing. No
account, no token: GitHub answers 60 requests an hour to a machine without one."""

import json
import re
from dataclasses import replace
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit

import httpx2

from app.skills import (
    LICENSES,
    RUNNERS,
    Found,
    SkillError,
    blob_id,
    capped,
    first_line,
    left_out_dir,
    left_out_file,
    made,
)

HOSTS = frozenset({"github.com", "api.github.com", "raw.githubusercontent.com"})
MAX_LISTING = 10 * 1024 * 1024
SECONDS = 20.0
ADDRESS = re.compile(
    r"(?:https://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?"
    r"(?:/tree/([^/@\s]+)(?:/([^@\s]*))?)?/?(?:@([0-9a-f]{40}))?")
NOT_AN_ADDRESS = (
    "not a GitHub address KOLONİ reads: https://github.com/<owner>/<repository>, or "
    "/tree/<branch>/<folder> after it")
# Names Windows keeps for devices, whatever comes after a dot (as `ntpath.isreserved`).
RESERVED = frozenset({"con", "prn", "aux", "nul", "conin$", "conout$",
                      *(f"{device}{n}" for device in ("com", "lpt") for n in "123456789¹²³")})
# A part like "LONGRE~1.MD" may be another file's 8.3 short name on NTFS: the same file.
SHORT_NAME = re.compile(r"~\d")
LINK, SUBMODULE = "120000", "160000"


def refusal(status: int, headers) -> str:
    """What GitHub's refusal means, in plain words."""
    if status == 429 or (status == 403 and headers.get("x-ratelimit-remaining") == "0"):
        return ("GitHub's limit for a machine without an account is reached (60 an hour): "
                "try again later")
    if status == 404:
        return "not found on GitHub: KOLONİ reads public repositories only"
    return f"GitHub answered {status}"


def fetch(url: str, limit: int) -> bytes:
    """GET one address of GitHub's, at most `limit` bytes: the one place KOLONİ reaches
    GitHub (a test puts its own in its place). No account, no redirect, a timeout."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS:
        raise SkillError(f"only GitHub is asked for a skill, not {parts.hostname}")
    try:
        # (trust_env off: no .netrc of the user's is sent along - no account, as said)
        with (httpx2.Client(timeout=SECONDS, follow_redirects=False, trust_env=False,
                            headers={"User-Agent": "KOLONI"}) as client,
              client.stream("GET", url) as answer):
            if answer.status_code != 200:
                raise SkillError(refusal(answer.status_code, answer.headers))
            data = bytearray()
            for chunk in answer.iter_bytes():
                data += chunk
                if len(data) > limit:
                    raise SkillError("GitHub sent more than was listed: it is not taken")
    except httpx2.HTTPError as exc:
        raise SkillError(f"GitHub could not be reached: {exc}") from None
    return bytes(data)


def _json(url: str) -> dict:
    try:
        return json.loads(fetch(url, MAX_LISTING))
    except ValueError:
        raise SkillError("GitHub's answer could not be read") from None


def safe_path(rel: str) -> bool:
    """Whether a path of the repository is one a file of this machine may have."""
    if any(char in '\\:<>"|?*' or ord(char) < 32 for char in rel) or rel.startswith("/"):
        return False
    return all(
        part not in ("", ".", "..") and part == part.rstrip(" .")
        and part.partition(".")[0].rstrip(" ").casefold() not in RESERVED
        and not SHORT_NAME.search(part)
        and len(part.encode("utf-16-le", "surrogatepass")) <= 2 * 255  # (NTFS's longest)
        for part in rel.split("/"))


def _blob(raw: str, rel: str, listed: tuple[str, int]) -> bytes:
    data = fetch(raw + quote(rel), listed[1])
    if blob_id(data) != listed[0]:
        raise SkillError(f"{rel} is not what was listed: read it again")
    return data


def listing(address: str) -> Found:  # noqa: C901
    """A skill's listing on GitHub, from one commit - pinned by `@<commit>` at the end of
    the address, else the branch's (or the default branch's) as it is now. What is read
    before the user's yes: the listing, the SKILL.md, the licence and the scripts."""
    match = ADDRESS.fullmatch(address.strip())
    if match is None:
        raise SkillError(NOT_AN_ADDRESS)
    owner, repo, ref, sub, pinned = match.groups()
    api = f"https://api.github.com/repos/{owner}/{repo}"
    sha = pinned or str(_json(
        f"{api}/commits/{quote(ref or str(_json(api)['default_branch']), safe='')}")["sha"])
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SkillError("GitHub's answer could not be read")
    # shortcut: a branch with "/" in its name is not told from the folder after it; pin
    # the commit (@<sha>) for one.
    tree = _json(f"{api}/git/trees/{sha}?recursive=1")
    if tree.get("truncated"):
        raise SkillError("the repository is too large to list: name a smaller one")
    prefix = f"{sub.strip('/')}/" if sub and sub.strip("/") else ""
    listed: dict[str, tuple[str, int]] = {}
    skipped: list[str] = []
    roots = {}
    for entry in tree.get("tree", []):
        path, kind, mode = str(entry.get("path", "")), entry.get("type"), entry.get("mode")
        if kind == "blob" and path in LICENSES:
            roots[path] = (str(entry["sha"]), int(entry["size"]))
        if not path.startswith(prefix):
            continue
        rel = path[len(prefix):]
        if not safe_path(rel):
            raise SkillError(f"{rel!r} is a path no file of this machine may have")
        parts = rel.split("/")
        if any(left_out_dir(part) for part in parts[:-1]):
            continue  # (its folder is said once, below)
        if kind == "tree":
            if left_out_dir(parts[-1]):
                skipped.append(f"{rel}/")
        elif kind != "blob" or mode in (LINK, SUBMODULE) or left_out_file(parts[-1]):
            skipped.append(rel)
        else:
            listed[rel] = (str(entry["sha"]), int(entry["size"]))
    capped(listed)
    base = f"https://raw.githubusercontent.com/{owner}/{repo}/{sha}/"
    wanted = [rel for rel in listed
              if rel in ("SKILL.md", *LICENSES) or PurePosixPath(rel).suffix.lower() in RUNNERS]
    contents = {rel: _blob(base + prefix, rel, listed[rel]) for rel in wanted}
    licence = None
    if prefix and not any(name in contents for name in LICENSES):
        found = next((name for name in LICENSES if name in roots), None)
        licence = first_line(_blob(base, found, roots[found])) if found else None
    source = f"https://github.com/{owner}/{repo}" + (f"/tree/{ref}" if ref else "") + (
        f"/{prefix.rstrip('/')}" if prefix else "") + f"@{sha}"
    return made(source, listed, contents, skipped, licence, (owner, repo, sha, prefix))


def rest(found: Found) -> Found:
    """The files of a listed skill not read yet, downloaded from the listed commit and each
    checked against the listing: what the card showed is what is kept."""
    assert found.repo is not None
    owner, repo, sha, prefix = found.repo
    base = f"https://raw.githubusercontent.com/{owner}/{repo}/{sha}/{prefix}"
    more = {rel: _blob(base, rel, listed) for rel, listed in found.listed.items()
            if rel not in found.contents}
    return replace(found, contents={**found.contents, **more})
