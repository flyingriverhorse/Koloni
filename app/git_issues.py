"""Item 57: a chat started from a GitHub issue - read with the user's own gh, never a token.
Beside `app.git` (that file is at its size limit); gh is started as `git.gh` finds it."""

import json
import re
import tempfile
from pathlib import Path

from app import git

# --- Item 57: a chat started from a GitHub issue - read with the user's own gh, never a token --
# shortcut: gh issue JSON fields not measured live (`gh issue list/view --json`, as gh's manual
# names them), measure once with the user's OK.
ISSUE_URL = re.compile(r"https://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)/issues/(\d{1,9})")
ISSUE_SECONDS = 30.0  # (gh asks GitHub: longer than a look at the repository)
MOST_ISSUE = 20_000  # characters of an issue's text, its comments with it
# (read_attachment gives 400 lines at once: the whole issue, its frame with it, in one read)
MOST_LINES = 380
CUT = "\n…(cut: the rest is on GitHub)"


def issue_ref(raw: str) -> str:
    """What gh is given for an issue the user names: its number in the project's repository
    (`#12`, `12`) or its address on github.com - written anew from what was matched, so
    nothing else reaches gh's command line. Refused, for anything else."""
    raw = raw.strip()
    if number := re.fullmatch(r"#?(\d{1,9})", raw):
        return str(int(number[1]))
    # (Nor a name of dots alone - a way up - or one that starts as an option.)
    if (found := ISSUE_URL.fullmatch(raw)) and not any(
        name.strip(".") == "" or name.startswith("-") for name in (found[1], found[2])
    ):
        return f"https://github.com/{found[1]}/{found[2]}/issues/{int(found[3])}"
    raise git.Refused(
        "an issue is its number (#12) or its address (https://github.com/owner/repo/issues/12)"
    )


def _gh_json(project: Path, *args: str) -> object:
    """What a read-only `gh issue` command answers, as JSON. Refused, with why."""
    # shortcut: what gh writes is read whole, bounded by its time (`ISSUE_SECONDS`) alone - `run`
    # reads with `communicate`; read in pieces and stop at a few MB if a huge answer is seen.
    # shortcut: gh runs in the project with its git hooks off (`_gh_env`), so a project that is no
    # git repository's top folder opens no issue, not even by address; run it elsewhere if asked.
    command = git.gh()
    if command is None:
        raise git.Refused(git.NO_GH)
    with tempfile.TemporaryDirectory(prefix="no-hooks-") as empty:
        env = git._gh_env(project, empty)
        if git.run([*command, "auth", "status"], project, git.SHORT_SECONDS, program="gh", **env)[
            0
        ]:
            raise git.Refused(git.NOT_IN)
        code, out, said = git.run(
            [*command, "issue", *args], project, ISSUE_SECONDS, program="gh", **env
        )
    if code != 0:
        raise git.Refused(f"gh issue {args[0]} failed: {git._text(out, said)[-git.TAIL :]}")
    try:
        return json.loads(out.decode("utf-8", "replace"))
    except ValueError:
        raise git.Refused(f"gh issue {args[0]} said no JSON") from None


def issues(project: Path) -> tuple[list[dict], str | None]:
    """The open issues of the project's GitHub repository, latest first (gh's own order) - or
    none and why: gh not installed or logged in, no GitHub remote, gh failed."""
    name, why = git.gh_repo(project)
    if name is None:
        return [], why
    # shortcut: the first 30 open issues, no search or paging; add them when a repository's list
    # is seen to be longer than that and the one wanted is not pasted.
    try:
        found = _gh_json(
            project,
            "list",
            f"--repo={name}",
            "--state=open",
            "--limit=30",
            "--json=number,title,url,updatedAt",
        )
    except git.Refused as refused:
        return [], str(refused)
    return [
        {
            "number": one["number"],
            "title": str(one.get("title") or ""),
            "url": str(one.get("url") or ""),
            "updated_at": one.get("updatedAt"),
        }
        for one in found
        if isinstance(one, dict) and isinstance(one.get("number"), int)
    ] if isinstance(found, list) else [], None


def issue(project: Path, ref: str) -> dict:
    """One issue (`issue_ref`'s): its number, its address, and its text - title, state,
    author, body, then each comment, oldest first - cut at `MOST_ISSUE`. One by number is of
    the project's repository; one by address of any. Refused, with why."""
    ref = issue_ref(ref)
    if ref.isdigit():
        name, why = git.gh_repo(project)
        if name is None:
            raise git.Refused(why)
        args = [ref, f"--repo={name}"]
    else:
        args = [ref]
    found = _gh_json(project, "view", *args, "--json=number,title,body,url,state,author,comments")
    if not isinstance(found, dict) or not isinstance(found.get("number"), int):
        raise git.Refused("gh issue view said no issue")

    def who(one: dict) -> str:
        author = one.get("author")
        return str(author.get("login") or "?") if isinstance(author, dict) else "?"

    url, state = str(found.get("url") or ""), str(found.get("state") or "").lower()
    parts = [
        f"Issue #{found['number']}: {found.get('title') or ''}",
        f"{url} ({state}, opened by {who(found)})",
        "",
        str(found.get("body") or "").strip() or "(no text)",
    ]
    for one in found.get("comments") or []:
        if isinstance(one, dict):
            parts += ["", f"--- {who(one)} commented:", str(one.get("body") or "").strip()]
    lines = "\n".join(parts).splitlines()  # (as read_attachment counts them)
    text = "\n".join(lines)
    # shortcut: cut from the end - the newest comments go first; keep the body and the latest
    # comments, cutting the middle, if a long thread's end is seen to matter.
    if len(text) > MOST_ISSUE or len(lines) > MOST_LINES:
        text = "\n".join(text[: MOST_ISSUE - len(CUT)].split("\n")[: MOST_LINES - 1]) + CUT
    return {"number": found["number"], "url": url, "text": text}
