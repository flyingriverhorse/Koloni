"""K-bilgi 8: this project's code as a knowledge (`knowledge.CODE`, "This project's code") - a scan
with the standard library and no model, so it costs nothing. Python through `ast` (a big file line
by line, `MAX_PARSED`; one that looks generated is skipped): its imports,
its top-level functions and classes and their methods (`Class.method`), and its calls by name or
attribute name (`self.x()` too); JS/TS by a light regex: `… from '…'`, `export function|class|
const …`, `function name(`, `class X`'s methods, and `name(` (`this.name(` too) as a call.
It is kept in `.koloni/knowledge/code/`: `graph.json` (each file's symbols, imports and calls with
its time, and the edges: a name's callers by file:line, a file's imports and importers, its tests)
and `guide.md`, a line for each file (defines …, imported by …, tests: …). A rescan reads again
only the files whose time changed. Agents have it as any knowledge: `lookup` answers who calls a
name or where it is defined (`lookup`), and a Map role's brief has a line for each name or file
its task names (`about`).
shortcut: calls are matched by name only (any `x.save()` is a caller of every `save`), and a name
defined twice is both - its callers are said "maybe"; follow the imports if that is seen to
mislead."""

import ast
import functools
import json
import posixpath
import re
import warnings
from collections.abc import Collection
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from app import knowledge, koloni, project_files, web
from app.project_view import MAX_TOTAL_BYTES, UNREAD_FOLDERS
from app.views import Refused

WHERE = f"{knowledge.FOLDER}/code"  # in `.koloni/`: `knowledge.folder_of` a code knowledge
GRAPH = "graph.json"
# graph.json's shape: a scan of another reads every file again (2: methods, B-371).
VERSION = 2
WHAT = "scan of the project's code"
SCANNED = "a scan of the code, no model"
PYTHON = (".py",)
SCRIPT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
MAX_FILES = 3_000
MAX_ENTRIES = 40_000  # entries of the project looked at
MAX_BYTES = 4 * 2**20  # a larger file is skipped
# A larger Python file is read line by line (`_lines`): `ast` takes some 700 times its size
# (app/agent.py, 1.3 MB, fits).
MAX_PARSED = 3 * 2**19
MAX_READ = MAX_TOTAL_BYTES  # read in one scan: past it, files are left for the next
# graph.json at most: past it a name keeps its first `MOST_CALLERS` callers and a file only its
# calls of the names defined here.
# shortcut: under `.koloni/`, graph.json is a standing file (`project_view.standing`) read whole
# at each watch, as a learned knowledge's pages are; keep KOLONİ's own derived files out of that
# set if it is seen to slow turns down.
MAX_GRAPH = 64 * 2**20
MOST_CALLERS = 50
GENERATED = ("_pb2.py", "_pb2_grpc.py")
# guide.md and learned.json are read as any of `.koloni/`'s files: 256 KiB at most.
MAX_GUIDE = 150_000
MAX_LOGGED = 1_000  # files named in learned.json's list (the page's Pages)
SHOWN = 6  # names in one list of a line, then "+N"
MOST_NAMED = 5  # names and files of a task, a line each in its brief
GITIGNORE = "# KOLONİ's scan of the code: made again by Rescan, not in the project's git.\n*"
TEST_FOLDERS = frozenset({"tests", "test", "__tests__", "e2e"})
NOT_CALLS = frozenset({"if", "for", "while", "switch", "catch", "function", "return", "typeof",
                       "await", "super", "import", "require", "with", "elif", "and", "or",
                       "not", "in", "print"})
FROM = re.compile(r"""\bfrom\s*['"]([^'"\n]+)['"]|\bimport\s*\(?\s*['"]([^'"\n]+)['"]""")
EXPORTED = re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?(function\*?|class|const|let|var)"
                      r"\s+([A-Za-z_$][\w$]*)")
FUNCTION = re.compile(r"^\s*(?:async\s+)?function\*?\s+([A-Za-z_$][\w$]*)\s*\(")
CLASS = re.compile(r"^(\s*)(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)")
METHOD = re.compile(r"^(\s+)(?:(?:async|static|public|private|protected|override|get|set)\s+)*"
                    r"\*?#?([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\([^)]*\)\s*(?::[^={]+)?\{\s*$")
PY_DEF = re.compile(r"(?:async\s+)?(def|class)\s+([A-Za-z_]\w*)")
PY_IMPORT = re.compile(r"\s*(?:from\s+(\.*[\w.]*)\s+)?import(?=[\s(])\s*\(?\s*([\w., ]*)")
CALL = re.compile(r"([A-Za-z_$][\w$]*)\s*\(")
NAME = re.compile(r"[A-Za-z_$][\w$]*")
WORD = re.compile(r"`([^`\n]{1,200})`|([\w$./-]+(?:\(\))?)")


# --- the scan -------------------------------------------------------------------------------


def _walk(root: str, within: Collection[str] | None = None) -> tuple[list[str], int]:
    """The code files of the project, folder by folder, as its file tools see it (`listing`: no
    secret, link or place KOLONİ never opens) - not into others' code or build output
    (`UNREAD_FOLDERS`), `.koloni/`, nor Claude Code's worktrees (whole checkouts); and how many
    were left past `MAX_FILES`. `within`: the only paths gone into (a local folder's, as
    `knowledge._counted` counted it)."""
    files, todo, looked, left = [], [""], 0, 0
    while todo and looked < MAX_ENTRIES:
        rel = todo.pop(0)
        try:
            entries = project_files.listing(root, rel)
        except Refused:
            continue
        for one in entries:
            looked += 1
            path, name = f"{rel}/{one['name']}" if rel else one["name"], one["name"].casefold()
            if within is not None and path not in within:
                continue
            if one["kind"] == "dir":
                if name not in UNREAD_FOLDERS and path.casefold() != koloni.FOLDER and not (
                        name == "worktrees" and rel.rsplit("/", 1)[-1].casefold() == ".claude"):
                    todo.append(path)
            elif name.endswith(PYTHON + SCRIPT) and ".min." not in name:  # (minified: built)
                if len(files) < MAX_FILES:
                    files.append(path)
                else:
                    left += 1
    return files, left


def _python(text: str) -> dict | None:
    """A Python file's facts: its top-level functions and classes, what it imports
    (`module:name`, a relative one with its dots) and the names it calls; None: it does not
    parse."""
    try:
        with warnings.catch_warnings():  # (an old file's "\d": not this scan's to say)
            warnings.simplefilter("ignore")
            tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    defs = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            defs.append([node.name, "function", node.lineno])
        elif isinstance(node, ast.ClassDef):
            defs.append([node.name, "class", node.lineno])
            defs += [[f"{node.name}.{one.name}", "method", one.lineno] for one in node.body
                     if isinstance(one, ast.FunctionDef | ast.AsyncFunctionDef)]
    imports: list[str] = []
    calls: dict[str, set[int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports += [one.name for one in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            imports += [f"{base}:{one.name}" for one in node.names]
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else None)
            if name:
                calls.setdefault(name, set()).add(node.lineno)
    return {"defs": defs, "imports": imports,
            "calls": {name: sorted(lines) for name, lines in calls.items()}}


def _lines(text: str, python: bool) -> dict:
    """A JS/TS file's facts - or a Python file's too big for `ast` (top-level `def` and `class`,
    `import` and `from … import`) - line by line, each call's line once.
    shortcut: a regex, not a parser - a name in a comment or a string is read as code; a JS
    method is an indented `name(…) {` line in a `class` (no braces counted), and a big Python
    file's methods are not read."""
    defs, imports, calls = [], [], {}
    klass: tuple[str, int] | None = None  # (the JS class the lines are in, and its indent)
    for at, line in enumerate(text.splitlines(), 1):
        name = None
        if python:
            if made := PY_IMPORT.match(line):
                base, names = made.groups()
                names = [one.split(" as ")[0].strip() for one in names.split(",") if one.strip()]
                imports += names if base is None else [f"{base}:{one}" for one in names or [""]]
            if made := PY_DEF.match(line):
                name = made.group(2)
                defs.append([name, "class" if made.group(1) == "class" else "function", at])
        else:
            imports += [one or two for one, two in FROM.findall(line)]
            indent = len(line) - len(line.lstrip())
            if klass and line.lstrip().startswith("}") and indent <= klass[1]:
                klass = None
            if made := EXPORTED.match(line) or FUNCTION.match(line):
                name = made.group(made.lastindex or 1)
                defs.append([name, made.group(1) if made.re is EXPORTED else "function", at])
            if made := CLASS.match(line):
                klass = (made.group(2), len(made.group(1)))
                if name is None:
                    name = made.group(2)
                    defs.append([name, "class", at])
            elif klass and (made := METHOD.match(line)) and 0 < len(made.group(1)) - klass[
                    1] <= 4 and made.group(2) not in NOT_CALLS:
                name = made.group(2)
                defs.append([f"{klass[0]}.{name}", "method", at])
        for called in dict.fromkeys(CALL.findall(line)):
            if called not in NOT_CALLS and called != name:
                calls.setdefault(called, []).append(at)
    return {"defs": defs, "imports": imports, "calls": calls}


def _facts(root: str, rel: str) -> tuple[dict | None, str]:
    """A file's facts (None: skipped, and why)."""
    if rel.casefold().endswith(GENERATED):
        return None, "it looks generated"
    try:
        data = project_files.bytes_of(root, rel, MAX_BYTES)
    except Refused as exc:
        return None, str(exc)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, "it is not UTF-8 text"
    if "generated" in text[:300].split("\n", 1)[0].casefold():  # ("# Generated by …")
        return None, "it looks generated"
    if not rel.casefold().endswith(PYTHON):
        return _lines(text, python=False), ""
    # shortcut: `ast` in this process, a 1.5 MB file at most (about 1 GB for a moment); parse in
    # a subprocess of its own if a bigger one is to be read whole.
    if len(data) > MAX_PARSED:
        return _lines(text, python=True), ""
    return (found, "") if (found := _python(text)) else (None, "it does not parse as Python")


def _module(rel: str) -> list[str]:
    parts = rel.rsplit(".", 1)[0].split("/")
    return parts[:-1] if parts[-1] == "__init__" else parts


def _python_target(rel: str, raw: str, modules: dict[str, str]) -> str | None:
    """The project's file a Python import names (`module:name`: the name's own module first).
    shortcut: modules by their path from the project's root - a `src/` layout's are not found."""
    base, _, name = raw.partition(":")
    dots = len(base) - len(base.lstrip("."))
    if dots:
        package = _module(rel) if rel.endswith("__init__.py") else _module(rel)[:-1]
        base = ".".join([*package[:len(package) - dots + 1], base.lstrip(".")]).strip(".")
    tried = [f"{base}.{name}".strip("."), base] if name and name != "*" else [base]
    return next((modules[one] for one in tried if one in modules), None)


def _script_target(rel: str, raw: str, files: set[str]) -> str | None:
    """The project's file a relative JS/TS import names (a package's: none)."""
    if not raw.startswith("."):
        return None
    base = posixpath.normpath(posixpath.join(posixpath.dirname(rel), raw))
    stem = base.rsplit(".", 1)[0] if base.endswith(SCRIPT) else base  # (`./x.js` is x.ts)
    tried = [base, *(stem + one for one in SCRIPT), *(f"{base}/index{one}" for one in SCRIPT)]
    return next((one for one in tried if one in files), None)


def tested(rel: str) -> str | None:
    """The module a test file is of by its name (tests/test_server.py, server.test.ts: server);
    None: it is not a test."""
    path = PurePosixPath(rel)
    stem = path.name.split(".")[0]
    if stem in ("__init__", "conftest"):  # (a package's own, not a test of `app/__init__.py`)
        return None
    if stem.startswith("test_"):
        return stem[5:]
    if stem.endswith("_test"):
        return stem[:-5]
    if re.search(r"\.(test|spec)\.", path.name) or TEST_FOLDERS & {
            one.casefold() for one in path.parts[:-1]}:
        return stem
    return None


def _edges(files: dict[str, dict]) -> dict:
    """What the files' facts say of each other: each file's imports and importers, its tests (by
    name, and a test that imports it), and each name defined here, its callers by file:line."""
    modules = {".".join(_module(rel)): rel for rel in files if rel.endswith(PYTHON)}
    names, defined = set(files), _defined(files)
    imports, imported_by, callers, by_name = {}, {}, {}, {}
    for rel, facts in files.items():
        targets = {_python_target(rel, raw, modules) if rel.endswith(PYTHON)
                   else _script_target(rel, raw, names) for raw in facts["imports"]}
        imports[rel] = sorted(one for one in targets if one and one != rel)
        for one in imports[rel]:
            imported_by.setdefault(one, []).append(rel)
        for name, lines in facts["calls"].items():
            if name in defined:
                callers.setdefault(name, []).extend(f"{rel}:{line}"
                                                    for line in dict.fromkeys(lines))
        if (of := tested(rel)) is not None:  # (a Python test of a Python file, a JS one of JS)
            by_name.setdefault((of, rel.endswith(PYTHON)), []).append(rel)
    tests = {}
    for rel in files:
        if tested(rel) is None and (found := list(dict.fromkeys(
                by_name.get((PurePosixPath(rel).name.split(".")[0], rel.endswith(PYTHON)), [])
                + [one for one in imported_by.get(rel, []) if tested(one) is not None]))):
            tests[rel] = found
    return {"imports": imports, "imported_by": imported_by, "callers": callers, "tests": tests}


def _bare(name: str) -> str:
    return name.rsplit(".", 1)[-1]  # (a method's own name: `Handler._json` is `_json`)


def _defined(files: dict[str, dict]) -> set[str]:
    """The names defined in the files: a method as `Class.method` and as `method` (calls are by
    the bare name)."""
    return {one for facts in files.values() for name, *_ in facts["defs"]
            for one in (name, _bare(name))}


def _listed(items: list[str], most: int = SHOWN) -> str:
    return ", ".join(items[:most]) + (f" +{len(items) - most}" if len(items) > most else "")


def section(rel: str, graph: dict) -> str:
    """A file's line: what it defines (and where; its methods after its top-level names),
    imports, is imported by, and its tests."""
    defs = sorted(graph["files"][rel]["defs"], key=lambda one: one[1] == "method")
    said = [f"defines {_listed([f'{name} ({line})' for name, _kind, line in defs])}"
            if defs else ""]
    for label, key in (("imports", "imports"), ("imported by", "imported_by"),
                       ("tests:", "tests")):
        if found := graph[key].get(rel):
            said.append(f"{label} {_listed(found)}")
    return f"{rel}: " + (" · ".join(one for one in said if one) or "nothing found")


def scan(root: str, known: dict, code: str | None = None, where: str | None = None,
         within: Collection[str] | None = None) -> dict:
    """Scan the project's code - again only the files whose time changed since the last scan -
    and write its graph, its guide (a line a file) and learned.json (`Learned`'s shape: the
    files scanned and skipped, no money spent). Returns learned.json's record. Refused: one could
    not be written. `code`: the folder scanned where it is not the project - a repository a
    knowledge cloned, its files by their paths in it: only its graph is written, in `where` (the
    knowledge's `knowledge.KEPT`), and what was scanned and skipped returned. `within`:
    `_walk`'s."""
    when = datetime.now(UTC).isoformat()
    where = where or knowledge.folder_of(known)
    walked_root = code or root
    top = Path(walked_root).resolve()
    walked, left = _walk(walked_root, within)
    last = graph(root, where) or {}
    old = (last.get("files") or {}) if last.get("version") == VERSION else {}
    files, skipped, again, read = {}, [], 0, 0
    for rel in walked:
        try:
            stat = (top / rel).stat()
        except OSError:
            continue
        stamp = stat.st_mtime_ns
        kept = old.get(rel)
        if isinstance(kept, dict) and _shaped(kept) and kept["mtime_ns"] == stamp:
            files[rel] = kept
            continue
        if read + stat.st_size > MAX_READ:
            left += 1
            continue
        read += stat.st_size
        facts, why = _facts(walked_root, rel)
        again += 1
        if facts is None:
            skipped.append({"source": rel, "read": False, "why": why})
        else:
            files[rel] = {"mtime_ns": stamp, **facts}
    found = {"version": VERSION, "scanned_at": when, "files": files, **_edges(files)}
    # (In bytes, with the line end `koloni.write` adds: as `_read` reads it.)
    if len((written := json.dumps(found, separators=(",", ":"))).encode()) >= MAX_GRAPH:
        found = _trimmed(found)
        written = json.dumps(found, separators=(",", ":"))
    koloni.write(root, f"{where}/{GRAPH}", written)
    symbols = sum(len(facts["defs"]) for facts in files.values())
    if code is not None:
        return {"scanned": len(files), "symbols": symbols, "skipped": skipped, "unread": left}
    koloni.write(root, f"{WHERE}/.gitignore", GITIGNORE)
    text = (f"# This project's code\n\nKOLONİ scanned {len(files)} files of it ({symbols} "
            "symbols), with no model: a line for each file - what it defines (at which line), "
            "imports and is imported by, and its tests, found by name. Ask lookup who calls a "
            "name or where it is defined.\n")
    for at, rel in enumerate(files):
        line = "\n- " + section(rel, found)
        if len(text) + len(line) > MAX_GUIDE:
            text += f"\n- … {len(files) - at} files more: ask lookup."
            break
        text += line
    koloni.write(root, f"{WHERE}/{knowledge.GUIDE}", text)
    record = {
        "learned_at": when, "sources": known["sources"], "model": SCANNED,
        "pages": [{"source": rel, "read": True, "why": None} for rel in files][:MAX_LOGGED]
        + skipped[:knowledge.MAX_LOG],
        "unread": left, "parts": [], "guide_from": len(files), "left": 0,
        "cost": {"amount": 0, "currency": "USD"}, "symbols": symbols, "scanned_again": again,
        "removed": known.get("removed") or []}
    koloni.write(root, f"{WHERE}/{knowledge.LEARNED}", json.dumps(record, indent=1))
    return record


def _trimmed(found: dict) -> dict:
    """A graph past `MAX_GRAPH`, smaller: a name's first `MOST_CALLERS` callers and how many it
    has, and a file's calls of the names defined here only.
    shortcut: so a call of a name defined later, in a file added since, is seen only once the
    calling file changes again."""
    defined = _defined(found["files"])
    return {**found, "files": {
        rel: {**facts, "calls": {name: lines for name, lines in facts["calls"].items()
                                 if name in defined}} for rel, facts in found["files"].items()},
            "callers": {name: calls[:MOST_CALLERS] for name, calls in found["callers"].items()},
            "callers_count": {name: len(calls) for name, calls in found["callers"].items()
                              if len(calls) > MOST_CALLERS}}


def _shaped(facts: object) -> bool:
    """Whether a file's facts kept in graph.json are as a scan writes them (a hand's edit, or an
    older scan's, is read again)."""
    try:
        return isinstance(facts, dict) and isinstance(facts["mtime_ns"], int) and all(
            isinstance(name, str) and isinstance(kind, str) and isinstance(line, int)
            for name, kind, line in facts["defs"]) and all(
            isinstance(one, str) for one in facts["imports"]) and all(
            isinstance(name, str) and all(isinstance(line, int) for line in lines)
            for name, lines in facts["calls"].items())
    except (TypeError, ValueError, KeyError, AttributeError):
        return False


# --- reading it -----------------------------------------------------------------------------

# What a graph.json not of a scan's shape raises as it is read: it is read as none.
BROKEN = (TypeError, ValueError, KeyError, AttributeError, IndexError)


def graph(root: str, where: str = WHERE) -> dict | None:
    """The last scan's graph (`where`: the folder in `.koloni/` it is kept in - a repository's
    knowledge's own); None: none, or not readable."""
    try:
        stamp = (Path(root).resolve() / koloni.FOLDER / where / GRAPH).stat().st_mtime_ns
    except OSError:
        return None
    return _read(str(Path(root).resolve()), where, stamp)


@functools.lru_cache(maxsize=4)
def _read(root: str, where: str, _stamp: int) -> dict | None:
    """Read once for each scan (`_stamp`: when graph.json was written)."""
    try:
        found = json.loads(project_files.bytes_of(
            root, f"{koloni.FOLDER}/{where}/{GRAPH}", MAX_GRAPH))
    except (Refused, ValueError, RecursionError):
        return None
    keys = ("files", "imports", "imported_by", "callers", "tests")
    return found if isinstance(found, dict) and all(
        isinstance(found.get(key), dict) for key in keys) else None


def _code_like(word: str) -> bool:
    """A word that reads as code, not English: a name with _ or an inner capital, a call, a
    dotted name, or a file of code."""
    return bool("_" in word or word.endswith("()") or "." in word or "/" in word
                or re.search(r"[a-z][A-Z]", word))


def named(text: str, found: dict, strict: bool) -> tuple[list[str], list[str]]:
    """The names defined in the code and its files a text names: in backticks, or as a word that
    reads as code - or (not `strict`) as any word.
    shortcut: a plain word names a symbol only in a question (`strict` off), so a task that says
    "run" or "main" is not taken for a function of that name."""
    defined = _defined(found["files"])
    names, files = [], []
    for quoted, word in WORD.findall(text):
        word = (quoted or word).strip().removesuffix("()").rstrip(".,:;")
        if not quoted and strict and not _code_like(word):
            continue
        if word.casefold().endswith(PYTHON + SCRIPT) or "/" in word:
            files += [rel for rel in found["files"] if rel == word or rel.endswith(f"/{word}")]
        elif word in defined and all(map(NAME.fullmatch, word.split("."))):
            names.append(word)  # (`Handler._json`: that method)
        elif (name := _bare(word)) in defined and NAME.fullmatch(name):
            names.append(name)
    return list(dict.fromkeys(names)), list(dict.fromkeys(files))


def _of(name: str, found: dict) -> tuple[list[str], list[str], list[str], int, str]:
    """Where a name is defined (`Class.method`: that method; a bare name: each of that name), its
    callers, its tests - the callers in a test, else the tests of the files it is defined in -
    how many callers more it has than are kept (`_trimmed`), and "" or why its callers are only
    maybe its own: other definitions share its bare name, which calls are matched by."""
    bare = _bare(name)
    same = [(f"{rel}:{line}", one) for rel, facts in found["files"].items()
            for one, _kind, line in facts["defs"] if _bare(one) == bare]
    defs = [at for at, one in same if one == name or "." not in name]
    maybe = f" (maybe: {len(same)} are named `{bare}`)" if len(same) > 1 else ""
    calls = found["callers"].get(bare, [])
    in_tests = [one for one in calls if tested(one.rsplit(":", 1)[0]) is not None]
    tests = in_tests or list(dict.fromkeys(
        one for at in defs for one in found["tests"].get(at.rsplit(":", 1)[0], [])))
    more = (found.get("callers_count") or {}).get(bare, len(calls)) - len(calls)
    return (defs, [one for one in calls if tested(one.rsplit(":", 1)[0]) is None], tests, more,
            maybe)


def lookup(root: str, question: str, where: str = WHERE) -> list[tuple[str, str]]:
    """What the scan says of a question: for each name it names, where it is defined, its callers
    (file:line) and its tests; for each file it names, its line; with neither, the files' lines
    that share most of its words. Each under the place it is about. `where`: as `graph`'s."""
    found = graph(root, where)
    if found is None:
        return []
    try:
        names, files = named(question, found, strict=False)
        parts = []
        for name in names:
            defs, callers, tests, more, maybe = _of(name, found)
            parts.append((defs[0], f"`{name}` is defined at {_listed(defs)}\n"
                                   f"callers {len(callers) + more}{maybe}: "
                                   f"{_listed(callers, 20) or 'none found'}"
                                   + (f" (+{more} more)" if more else "")
                                   + f"\ntests: {_listed(tests) or 'none found'}"))
        parts += [(rel, section(rel, found)) for rel in files]
        if not parts:  # (a question in words: the files whose line shares most of them)
            asked = knowledge._terms(question)
            scored = sorted(((-len(asked & knowledge._terms(line)), rel, line)
                             for rel in found["files"] if (line := section(rel, found))),
                            key=lambda one: one[:2])
            parts = [(rel, line) for score, rel, line in scored[:3] if score]
    except BROKEN:
        return []
    return [(where, part[:knowledge.LOOKED_CHARS]) for where, part in
            parts[:knowledge.MOST_LOOKED_UP]]


# A file a program starts from, by its name: first of a repository's code in its guide (`central`).
ENTRY = frozenset({"main", "__main__", "cli", "app", "__init__", "index", "server", "lib", "mod"})
# Others' code kept in a repository, or examples of it: no part of how its code works.
VENDORED = frozenset({"vendor", "vendored", "third_party", "thirdparty", "external", "examples",
                      "example", "fixtures", "testdata"})


def central(found: dict) -> list[str]:
    """A scanned repository's code files, the most central first: where a program starts (by its
    name, `ENTRY`), then those most files import - no test, vendored code, example or file of a
    hidden folder (.github/, a CLI's settings: not kept to read either, `knowledge._keep`); a
    generated or minified file is not scanned at all.
    shortcut: by name and importers only; weigh callers too if a hub of calls is seen ranked low."""
    files = [rel for rel in found["files"] if tested(rel) is None and not any(
        part.startswith(".") or part.casefold() in VENDORED for part in rel.split("/")[:-1])]
    return sorted(files, key=lambda rel: (PurePosixPath(rel).name.split(".")[0] not in ENTRY,
                                          -len(found["imported_by"].get(rel, [])),
                                          rel.count("/"), rel))


def about(root: str, task: str) -> list[str]:
    """A line for each name and file of the code a task names (in backticks or as code): where it
    is, its callers and its test - at most `MOST_NAMED`."""
    found = graph(root)
    if found is None:
        return []
    try:
        names, files = named(task, found, strict=True)
        lines = []
        for name in names:
            defs, callers, tests, more, maybe = _of(name, found)
            lines.append(f"`{name}` ({_listed(defs, 2)}): callers {len(callers) + more}{maybe}"
                         + (f" ({_listed(callers, 3)})" if callers else "")
                         + (f" · test {tests[0]}" if tests else ""))
        for rel in files:
            by, tests = found["imported_by"].get(rel, []), found["tests"].get(rel, [])
            lines.append(f"{rel}: imported by {len(by)}" + (f" ({_listed(by, 3)})" if by else "")
                         + (f" · tests {_listed(tests, 2)}" if tests else ""))
        return [web._line(line, 400) for line in lines[:MOST_NAMED]]
    except BROKEN:
        return []
