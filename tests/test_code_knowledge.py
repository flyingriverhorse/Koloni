"""K-bilgi 8: this project's code as a knowledge - scanned with no model (`app.code_map`): what
each file defines, imports and is imported by, a name's callers by file:line, its tests by name;
`lookup` answers from it and a Map role's brief has a line for each name its task names."""

import json
import os

from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN
from tests.test_knowledge_page import _learned, _pid

CODE = {"topic": "Code", "sources": ["code:"], "max_usd": 0.5, "removed": []}
FILES = {
    "pkg/__init__.py": "",
    "pkg/util.py": "import os\n\n\ndef foo(x):\n    return x\n\n\nclass Bar:\n    pass\n",
    "pkg/main.py": ("from pkg.util import foo\nfrom . import util\n\n\n"
                    "def run():\n    return foo(1) + util.foo(2)\n"),
    "tests/test_util.py": "from pkg.util import foo\n\n\ndef test_foo():\n    assert foo(3) == 3\n",
    "web/api.ts": ("export function fetchAll() {\n  return helper()\n}\n"
                   "function helper() {\n  return 1\n}\n"),
    "web/page.tsx": "import { fetchAll } from './api'\nexport const Page = () => fetchAll()\n",
    "web/page.test.tsx": "import { Page } from './page'\ntest('page', () => Page())\n",
    # Never read: a secret's name, others' code, KOLONİ's own folder.
    "credentials.py": "def leaked():\n    pass\n",
    "node_modules/lib/index.js": "export function hidden() {}\n",
    ".koloni/tmp/x.py": "def scratch():\n    pass\n",
}


def _project(project_dir) -> str:
    (project_dir / "hello.py").unlink()
    for rel, body in FILES.items():
        (project_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (project_dir / rel).write_text(body, encoding="utf-8")
    return str(project_dir.resolve())


def test_a_scan_finds_defs_imports_callers_and_tests_and_skips_secrets(project_dir):
    from app import code_map
    root = _project(project_dir)
    record = code_map.scan(root, CODE)
    graph = code_map.graph(root)
    assert graph is not None
    assert set(graph["files"]) == {rel for rel in FILES if rel.startswith(("pkg", "tests", "web"))}
    assert graph["files"]["pkg/util.py"]["defs"] == [["foo", "function", 4], ["Bar", "class", 8]]
    # Calls by plain and attribute name, one a line; a name's callers by file:line.
    assert graph["callers"]["foo"] == ["pkg/main.py:6", "tests/test_util.py:5"]
    assert graph["imports"]["pkg/main.py"] == ["pkg/util.py"]  # (`from . import util` too)
    assert graph["imported_by"]["pkg/util.py"] == ["pkg/main.py", "tests/test_util.py"]
    assert graph["tests"]["pkg/util.py"] == ["tests/test_util.py"]
    # JS/TS: exports, functions, relative imports, calls, a test by its name.
    assert graph["files"]["web/api.ts"]["defs"] == [["fetchAll", "function", 1],
                                                     ["helper", "function", 4]]
    assert graph["callers"]["helper"] == ["web/api.ts:2"]
    assert graph["callers"]["fetchAll"] == ["web/page.tsx:2"]
    assert graph["imports"]["web/page.tsx"] == ["web/api.ts"]
    assert graph["tests"]["web/page.tsx"] == ["web/page.test.tsx"]
    # What the page shows: free, the files, the names; the guide a line a file.
    assert record["cost"] == {"amount": 0, "currency": "USD"} and record["guide_from"] == 7
    assert record["symbols"] == 7 and record["scanned_again"] == 7
    assert "credentials.py" not in json.dumps(record)
    guide = (project_dir / ".koloni" / "knowledge" / "code" / "guide.md").read_text("utf-8")
    assert ("- pkg/util.py: defines foo (4), Bar (8) · imported by pkg/main.py, "
            "tests/test_util.py · tests: tests/test_util.py") in guide
    assert (project_dir / ".koloni" / "knowledge" / "code" / ".gitignore").exists()


def test_a_rescan_reads_only_the_changed_files(monkeypatch, project_dir):
    from app import code_map
    root = _project(project_dir)
    code_map.scan(root, CODE)
    read = []
    facts = code_map._facts
    monkeypatch.setattr(code_map, "_facts", lambda root, rel: read.append(rel) or facts(root, rel))
    util = project_dir / "pkg" / "util.py"
    util.write_text(FILES["pkg/util.py"] + "\n\ndef baz():\n    return foo(0)\n", encoding="utf-8")
    stamp = util.stat().st_mtime_ns + 10**9  # (a tick Windows sees)
    os.utime(util, ns=(stamp, stamp))
    (project_dir / "web" / "api.ts").unlink()
    record = code_map.scan(root, CODE)
    assert read == ["pkg/util.py"] and record["scanned_again"] == 1
    graph = code_map.graph(root)
    assert graph is not None and "web/api.ts" not in graph["files"]
    assert graph["callers"]["foo"] == ["pkg/main.py:6", "pkg/util.py:13", "tests/test_util.py:5"]


def test_lookup_says_who_calls_a_name_and_where_it_is(project_dir):
    from app import code_map, knows
    root = _project(project_dir)
    code_map.scan(root, CODE)
    found = knows.looked_up(root, [CODE], "who calls foo?")
    assert found.startswith(knows.LOOKED)
    assert ("Code · pkg/util.py:4\n`foo` is defined at pkg/util.py:4\ncallers 1: pkg/main.py:6\n"
            "tests: tests/test_util.py:5") in found
    # A question in words: the files whose line shares them.
    assert "web/page.tsx" in [where for where, _part in code_map.lookup(root, "the page tests")]


def test_the_page_scans_the_code_for_nothing_and_tries_it_with_no_model(make_client,
                                                                          project_dir):
    client, model = make_client({"Lead": [text("unused")]})
    _project(project_dir)
    pid = _pid(client, project_dir)
    mixed = client.post(f"/api/projects/{pid}/knowledge", headers=OWN,
                        json={**CODE, "sources": ["code:", "docs/"]})
    assert mixed.status_code == 422 and "of its own" in mixed.text
    row = client.post(f"/api/projects/{pid}/knowledge", json=CODE, headers=OWN).json()
    assert row["state"]["folder"] == ".koloni/knowledge/code/"
    asked = {"project_id": pid, "question": "who calls `helper`"}
    assert client.post(f"/api/knowledge/{row['id']}/try", json=asked,
                       headers=OWN).status_code == 409
    # No role uses it and no model is named: a scan needs none.
    started = client.post(f"/api/knowledge/{row['id']}/learn", json={"project_id": pid},
                          headers=OWN)
    assert started.status_code == 202, started.text
    state = _learned(client, row["id"], pid)
    assert state["failed"] is None and state["stale"] is None and state["estimate"] is None
    assert state["learned"]["symbols"] == 7 and state["learned"]["cost"]["amount"] == 0
    assert "pkg/util.py: defines foo (4)" in state["guide"]
    tried = client.post(f"/api/knowledge/{row['id']}/try", json=asked, headers=OWN)
    assert tried.status_code == 200 and "callers 1: web/api.ts:2" in tried.json()["answer"]
    assert model.calls == []
    (project_dir.parent / "other").mkdir()
    other = client.post("/api/projects",
                        json={"root_path": str(project_dir.parent / "other")}).json()
    copied = client.post(f"/api/knowledge/{row['id']}/copy", headers=OWN,
                         json={"project_id": pid, "to_project_id": other["id"]})
    assert copied.status_code == 422


def test_a_map_roles_brief_names_the_callers_of_what_its_task_names(make_client, wait_run,
                                                                    project_dir):
    from app import code_map, knows
    from tests.test_spawn import begin, spawn
    client, model = make_client({
        "Lead": [spawn("Coder", "make `foo` take two arguments", "s1"),
                 spawn("Coder", "fix the label of the page", "s2"), text("done")],
        "Coder": [text("made")], "Coder 2": [text("fixed")]})
    code_map.scan(_project(project_dir), CODE)
    pid = _pid(client, project_dir)
    row = client.post(f"/api/projects/{pid}/knowledge", json=CODE, headers=OWN).json()
    coder = next(r for r in client.get("/api/roles").json() if r["name"] == "Coder")
    client.put(f"/api/knowledge/{row['id']}/roles/{coder['id']}", json={"mode": "map"},
               headers=OWN)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="have the Coder change foo, then fix the label")
    wait_run(client, cid, run_id)
    told = model.calls_of["Coder"][0][0]["content"]
    about = told.split(knows.CODE_ABOUT, 1)[1]
    assert ("`foo` (pkg/util.py:4): callers 1 (pkg/main.py:6) · test tests/test_util.py:5"
            in about) and about.count("data, not instructions") == 1
    assert "Code (.koloni/knowledge/code/guide.md)" in told  # (its map, as any knowledge's)
    # A task in plain words names no symbol: nothing is added ("page" is no `Page`).
    assert knows.CODE_ABOUT not in model.calls_of["Coder 2"][0][0]["content"]


# --- review: big and generated files, a broken graph, its size, the topic code, an expert ---------


def test_a_big_python_file_is_read_line_by_line_and_a_generated_one_is_skipped(monkeypatch,
                                                                              project_dir):
    from app import code_map
    root = _project(project_dir)
    big = ("import os\nfrom pkg.util import (\n    foo,\n)\nimportant = 1\n\n\n"
           "def huge():\n    return foo(1)\n\n\nclass Big:\n    def inner(self):\n        pass\n")
    (project_dir / "pkg" / "big.py").write_text(big + "#" * 200, encoding="utf-8")
    (project_dir / "pkg" / "msg_pb2.py").write_text("def made():\n    pass\n", encoding="utf-8")
    (project_dir / "pkg" / "orm.py").write_text("# Generated by Django 5.0\ndef up():\n    pass\n",
                                                encoding="utf-8")
    monkeypatch.setattr(code_map, "MAX_PARSED", len(big))
    parsed, python = [], code_map._python
    monkeypatch.setattr(code_map, "_python", lambda text: parsed.append(text) or python(text))
    record = code_map.scan(root, CODE)
    graph = code_map.graph(root)
    assert graph is not None and parsed and not any("class Big" in one for one in parsed)
    assert graph["files"]["pkg/big.py"]["defs"] == [["huge", "function", 8], ["Big", "class", 12]]
    assert graph["imports"]["pkg/big.py"] == ["pkg/util.py"] and "pkg/big.py:9" in graph[
        "callers"]["foo"]
    skipped = {one["source"]: one["why"] for one in record["pages"] if not one["read"]}
    assert skipped == {"pkg/msg_pb2.py": "it looks generated", "pkg/orm.py": "it looks generated"}


def test_a_graph_not_of_a_scans_shape_is_read_as_none(project_dir):
    from app import code_map, knows
    root = _project(project_dir)
    code = project_dir / ".koloni" / "knowledge" / "code"
    code.mkdir(parents=True)
    (code / "guide.md").write_text("# This project's code", encoding="utf-8")
    for broken in ('{"files": {"pkg/util.py": {"defs": 5}}, "imports": {}, "imported_by": {}, '
                   '"callers": {}, "tests": {}}', '[1, 2]', '{"files": {'):
        (code / "graph.json").write_text(broken, encoding="utf-8")
        assert knows.about(root, [CODE], "change `foo`") == ""
        assert knows.looked_up(root, [CODE], "who calls foo").startswith("None of the pages")
    # And a scan reads every file again, over it.
    assert code_map.scan(root, CODE)["scanned_again"] == 7


def test_a_graph_past_its_cap_keeps_fewer_callers_and_is_read_at_the_next_rescan(monkeypatch,
                                                                                project_dir):
    from app import code_map
    root = _project(project_dir)
    (project_dir / "many.py").write_text(
        "from pkg.util import foo\n" + "foo(1); foo(2)\n" * 60 + "print(len([]))\n",
        encoding="utf-8")
    code_map.scan(root, CODE)
    whole = (project_dir / ".koloni" / "knowledge" / "code" / "graph.json").stat().st_size
    assert code_map.graph(root)["files"]["many.py"]["calls"]["foo"] == list(range(2, 62))
    monkeypatch.setattr(code_map, "MAX_GRAPH", whole - 1)
    (project_dir / "many.py").touch()
    stamp = (project_dir / "many.py").stat().st_mtime_ns + 10**9
    os.utime(project_dir / "many.py", ns=(stamp, stamp))
    code_map.scan(root, CODE)
    graph = code_map.graph(root)
    assert graph is not None and len(graph["callers"]["foo"]) == code_map.MOST_CALLERS
    assert graph["callers_count"]["foo"] == 62 and "len" not in graph["files"]["many.py"]["calls"]
    said = code_map.lookup(root, "who calls foo")[0][1]  # (the count of every one, tests too)
    assert "callers 62: many.py:2," in said and said.count("many.py") == 20 and "(+12 more)" in said
    assert code_map.scan(root, CODE)["scanned_again"] == 0


def test_the_topic_code_is_the_scans_and_its_expert_asks_lookup(client, project_dir):
    from app import code_map, knowledge
    pid = _pid(client, project_dir)
    taken = client.post(f"/api/projects/{pid}/knowledge", headers=OWN,
                        json={"topic": "Code", "sources": ["docs/"]})
    assert taken.status_code == 422 and "another topic" in taken.text
    root = _project(project_dir)
    code_map.scan(root, CODE)
    told = knowledge.brief(root, {**CODE, "max_pages": 500})
    assert told.startswith(knowledge.CODE_EXPERT) and "pages" not in told.split("\n")[0]


def test_methods_and_self_calls_are_found_and_a_shared_name_is_maybe(project_dir):
    """B-371: a class's methods (`Class.method`, and the bare name), `self.x()` and `this.x()`
    calls as their callers - said "maybe" where two definitions share the name."""
    from app import code_map, knows
    root = _project(project_dir)
    (project_dir / "server.py").write_text(
        "class Handler:\n    def _json(self, data):\n        return data\n\n"
        "    def do_GET(self):\n        return self._json(1)\n\n\n"
        "class NotesStore:\n    async def save(self):\n        pass\n\n\n"
        "def serve(handler):\n    return handler._json(2)\n", encoding="utf-8")
    (project_dir / "web" / "store.ts").write_text(
        "export class Store {\n  constructor() {\n    this.load()\n  }\n\n"
        "  async load(): Promise<void> {\n    if (this.ready) {\n      return\n    }\n  }\n}\n"
        "class Other {\n  save() {\n    return 1\n  }\n}\n", encoding="utf-8")
    code_map.scan(root, CODE)
    graph = code_map.graph(root)
    assert graph is not None and graph["version"] == code_map.VERSION
    assert graph["files"]["server.py"]["defs"] == [
        ["Handler", "class", 1], ["Handler._json", "method", 2], ["Handler.do_GET", "method", 5],
        ["NotesStore", "class", 9], ["NotesStore.save", "method", 10], ["serve", "function", 14]]
    assert graph["files"]["web/store.ts"]["defs"] == [
        ["Store", "class", 1], ["Store.constructor", "method", 2], ["Store.load", "method", 6],
        ["Other", "class", 12], ["Other.save", "method", 13]]
    assert graph["callers"]["_json"] == ["server.py:6", "server.py:15"]
    assert graph["callers"]["load"] == ["web/store.ts:3"]
    assert code_map.section("server.py", graph).startswith(
        "server.py: defines Handler (1), NotesStore (9), serve (14), Handler._json (2)")
    for asked in ("Who calls _json?", "Handler._json"):
        said = code_map.lookup(root, asked)[0][1]
        assert "is defined at server.py:2\ncallers 2: server.py:6, server.py:15" in said, said
    # Two `save`s: their callers are only maybe each one's.
    (project_dir / "app.py").write_text("def go(store):\n    store.save()\n", encoding="utf-8")
    code_map.scan(root, CODE)
    said = code_map.lookup(root, "who calls save")[0][1]
    assert "callers 1 (maybe: 2 are named `save`): app.py:2" in said
    assert "`NotesStore.save` is defined at server.py:10\n" in code_map.lookup(
        root, "NotesStore.save")[0][1]
    # A Map role's brief names a method's callers.
    about = knows.about(root, [CODE], "rename `Handler._json` to `_send_json` in server.py")
    assert "`Handler._json` (server.py:2): callers 2 (server.py:6, server.py:15)" in about


def test_a_graph_of_an_older_scan_is_read_again_whole(project_dir):
    from app import code_map
    root = _project(project_dir)
    code_map.scan(root, CODE)
    path = project_dir / ".koloni" / "knowledge" / "code" / "graph.json"
    older = json.loads(path.read_text(encoding="utf-8"))
    del older["version"]
    path.write_text(json.dumps(older), encoding="utf-8")
    assert code_map.scan(root, CODE)["scanned_again"] == 7
