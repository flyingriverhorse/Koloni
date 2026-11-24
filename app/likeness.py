"""Whether two To-do titles name the same work (B-403, B-407): the Scout's proposals and an
agent's add_task are told so (`app.backlog`)."""

import re
from types import SimpleNamespace

from app.memory import _like, search, words

# A file's name or path in a title, by its ending: "docs/usage.md", "test_server.py".
_FILE = re.compile(r"[\w./\\-]+\.[a-z]{1,5}\b", re.IGNORECASE)
# ...and a project's well-known files by their name alone: "the README" is README.md (B-407).
_KNOWN = re.compile(
    r"\b(readme|licen[cs]e|changelog|contributing|makefile|dockerfile)\b", re.IGNORECASE
)
# What any change of a file says: two tasks on one file are not alike by these words.
_ANY_CHANGE = re.compile(r"\b(add|update|fix|write|files?)\b", re.IGNORECASE)


def _files(title: str) -> set[str]:
    """The names of the files a title names, folded, without their folders ("app/parser.py"
    is "parser.py"); not "e.g." nor "U.S.": no path and two letters or fewer before the dot.
    A well-known one by its name alone, whatever its ending: README.md is "readme"."""
    title = title.replace("`", "")
    found = (re.split(r"[/\\]", path) for path in _FILE.findall(title))
    names = {
        parts[-1].casefold()
        for parts in found
        if len(parts) > 1 or len(parts[-1].split(".")[0]) > 2
    }
    return {stem if _KNOWN.fullmatch(stem := name.split(".")[0]) else name for name in names} | {
        known.casefold() for known in _KNOWN.findall(title)
    }


def alike(one: str, other: str) -> bool:
    """Whether either title is found by the other, by the memory's word matching: a short
    title ("Fix calc.average") is too few of a long one's words to find it. Two that name
    files, none of them by the same name, are not: "Add docs/usage.md" is not "Write
    docs/overview.md" (B-403); two on the same file that both say more than its name and
    "add" or "update" are not either unless they share a word of that (B-407).
    shortcut: a file is told by a short ending or a well-known name (`_KNOWN`), so "Node.js"
    or "obj.mean" is one too and "the license" is LICENSE; check the names against the
    project's files if tasks are seen apart wrongly."""
    files = [_files(one), _files(other)]
    if all(files):
        if not files[0] & files[1]:
            return False
        said = [
            words(_ANY_CHANGE.sub(" ", _KNOWN.sub(" ", _FILE.sub(" ", title.replace("`", "")))))
            for title in (one, other)
        ]
        if all(said) and not any(_like(word, own) for word in said[0] for own in said[1]):
            return False
    return any(
        search(query, [SimpleNamespace(about=None, text=text, observed_at=0)])
        for query, text in ((one, other), (other, one))
    )
