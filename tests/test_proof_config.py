"""0.1.7's Config, a kind of Check by kind of work: a JSON, YAML or TOML file a turn wrote parses -
else failed with its parser's first complaint and line - and a package.json, a pyproject.toml, a
GitHub workflow or a Compose file keeps the shape its tool reads (`proof_kinds.check_config`, no
model). A file nested too deep, YAML with aliases, or a secret file is never read; a sure problem
is a fix round, as the other kinds' are; Settings may switch it off, a kind left out is on."""

import json
import time

import pytest

from app import proof
from app.proof_kinds import MOST_DEPTH, check_config
from tests.fakes import ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import PASS, begin, texts

WORKFLOW = ".github/workflows/ci.yml"


def said(root, files: dict[str, str]) -> list[tuple[str, str]]:
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")
    return [(one["state"], one["text"]) for one in check_config(root, list(files))]


@pytest.mark.parametrize(
    ("rel", "body", "line"),
    [
        ("a.json", '{\n  "a": 1,\n  "b": \n}\n', "a.json:4: does not parse - Expecting value"),
        ("a.yaml", "a: 1\nb: [1, 2\nc: 3\n", "a.yaml:3: does not parse - expected ',' or ']'"),
        ("a.toml", 'name = "x"\nversion = \n', "a.toml:2: does not parse - Invalid value"),
        # (npm reads no comments: a package.json with one does not parse)
        ("package.json", '{\n  // the app\n  "name": "x"\n}\n', "package.json:2: does not parse"),
    ],
)
def test_a_file_that_does_not_parse_fails_with_its_parsers_line(tmp_path, rel, body, line):
    ((state, said_),) = said(tmp_path, {rel: body})
    assert state == "failed" and said_.startswith(line), said_


def test_files_that_parse_pass_and_json_with_comments_where_its_tool_reads_them(tmp_path):
    assert said(
        tmp_path,
        {
            "settings.json": '{"a": [1, 2]}',
            "tsconfig.json": '{\n  // strict\n  "compilerOptions": {"strict": true,},\n}\n',
            "k8s.yaml": "kind: A\n---\nkind: B\n",
            "ruff.toml": "line-length = 100\n",
        },
    ) == [
        ("passed", "settings.json: parses"),
        ("passed", "tsconfig.json: parses"),
        ("passed", "k8s.yaml: parses"),
        ("passed", "ruff.toml: parses"),
    ]


def test_a_package_json_keeps_npms_shape(tmp_path):
    good = {"name": "app", "version": "1.0.0", "scripts": {"test": "vitest"}}
    assert said(tmp_path, {"package.json": json.dumps(good)}) == [
        ("passed", "package.json: parses, as a package.json should")
    ]
    bad = {"name": 1, "version": "1", "scripts": {"test": "vitest", "build": ["tsc"]}}
    assert said(tmp_path, {"package.json": json.dumps(bad)}) == [
        ("failed", "package.json: name is not a string"),
        ("failed", "package.json: scripts.build is not a string"),
    ]
    assert said(tmp_path, {"web/package.json": '{"scripts": "vitest"}'}) == [
        ("failed", "web/package.json: scripts is not an object")
    ]
    assert said(tmp_path, {"package.json": "[]"}) == [("failed", "package.json: not a JSON object")]


def test_a_pyproject_has_its_projects_name_and_tables_of_tools(tmp_path):
    good = '[project]\nname = "app"\n\n[tool.ruff]\nline-length = 100\n'
    assert said(tmp_path, {"pyproject.toml": good}) == [
        ("passed", "pyproject.toml: parses, as a pyproject.toml should")
    ]
    bad = '[project]\nversion = "1"\n\n[tool]\nruff = 1\n'
    assert said(tmp_path, {"pyproject.toml": bad}) == [
        ("failed", "pyproject.toml: [project] has no name"),
        ("failed", "pyproject.toml: tool.ruff is not a table"),
    ]
    assert said(tmp_path, {"pyproject.toml": "[tool.pytest.ini_options]\n"}) == [
        ("passed", "pyproject.toml: parses, as a pyproject.toml should")  # (no [project]: fine)
    ]


def test_a_github_workflow_has_on_and_jobs_each_with_runs_on_and_steps_or_uses(tmp_path):
    good = (
        "name: ci\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: pytest\n  shared:\n    uses: org/repo/.github/workflows/x.yml@main\n"
    )
    assert said(tmp_path, {WORKFLOW: good}) == [
        ("passed", f"{WORKFLOW}: parses, as a GitHub workflow should")
    ]
    bad = "name: ci\njobs:\n  test:\n    steps: []\n  lint:\n    runs-on: x\n    steps: run\n"
    assert said(tmp_path, {WORKFLOW: bad}) == [
        ("failed", f"{WORKFLOW}: has no on: (what starts it)"),
        ("failed", f"{WORKFLOW}: job test has no runs-on or uses"),
        ("failed", f"{WORKFLOW}: job lint has no list of steps"),
    ]
    assert said(tmp_path, {WORKFLOW: "on: push\n"}) == [("failed", f"{WORKFLOW}: has no jobs")]


def test_a_compose_file_has_a_mapping_of_services(tmp_path):
    assert said(tmp_path, {"compose.yaml": "services:\n  web:\n    image: nginx\n"}) == [
        ("passed", "compose.yaml: parses, as a Compose file should")
    ]
    assert said(tmp_path, {"docker-compose.yml": "services:\n  - web\n"}) == [
        ("failed", "docker-compose.yml: services is not a mapping")
    ]
    assert said(tmp_path, {"docker-compose.dev.yml": "version: '3'\n"}) == [
        ("failed", "docker-compose.dev.yml: has no services")
    ]


def test_a_bomb_is_not_read(tmp_path):
    deep = MOST_DEPTH + 1
    rows = said(
        tmp_path,
        {
            "deep.json": "[" * deep + "]" * deep,
            "deep.yaml": "a: " + "[" * deep + "]" * deep + "\n",
            "deep.toml": "a = " + "[" * deep + "]" * deep + "\n",
            # (a billion laughs: one alias may stand for millions of nodes)
            "laughs.yml": "a: &a [x, x]\nb: &b [*a, *a]\nc: [*b, *b]\n",
            # (brackets in a string are no nesting)
            "fine.json": json.dumps({"a": "[" * deep}),
        },
    )
    deep_said = f"not checked: it nests over {MOST_DEPTH} deep"
    assert rows == [
        ("note", f"deep.json: {deep_said}"),
        ("note", f"deep.yaml: {deep_said}"),
        ("note", f"deep.toml: {deep_said}"),
        ("note", "laughs.yml: not checked: it uses YAML aliases, which are not read"),
        ("passed", "fine.json: parses"),
    ]


def test_a_secret_file_is_never_read(tmp_path):
    rows = said(tmp_path, {"secrets.json": "not json", "config/.env.json": "{"})
    assert rows == [
        ("note", "secrets.json: not checked: a secret file is never read"),
        ("note", "config/.env.json: not checked: a secret file is never read"),
    ]


def test_a_problem_the_file_had_before_the_turn_is_a_note(tmp_path):
    (tmp_path / "a.json").write_text("{", encoding="utf-8")
    rows = check_config(tmp_path, ["a.json"], before={"a.json": "{"})
    assert [(one["state"], one["text"].endswith(" - so before this turn")) for one in rows] == [
        ("note", True)
    ]


def test_config_is_a_part_on_by_default():
    assert "config" in proof.PARTS


# --- at a turn's end ------------------------------------------------------------------------

BROKEN = '{\n  "name": "app",\n  "scripts": {"test": "vitest",}\n}\n'
FIXED = '{\n  "name": "app",\n  "scripts": {"test": "vitest"}\n}\n'


@pytest.mark.no_po
def test_a_broken_package_json_is_a_fix_round_then_passes(make_client, wait_run, project_dir):
    client, model = make_client(
        [
            write("package.json", BROKEN),
            text("done"),
            write("package.json", FIXED, "w2"),
            text("fixed"),
        ],
        executor=ScriptedExecutor([PASS, PASS]),
    )
    cid, run_id = begin(client, project_dir, check_command="python check.py")
    snap = wait_run(client, cid, run_id)
    nudged = [
        str(m["content"])
        for m in model.calls[-1]
        if m["role"] == "user" and str(m["content"]).startswith("Not the end yet: KOLONİ's")
    ]
    assert len(nudged) == 1 and "package.json:3: does not parse" in nudged[0], nudged
    rows = texts(snap)
    assert "package.json: parses, as a package.json should" in rows, rows
    assert "Sent back to fix: 1 of 2 rounds (1 problem in what it wrote)" in rows, rows


@pytest.mark.no_po
def test_config_switched_off_checks_none_and_says_so(make_client, wait_run, project_dir):
    client, _model = make_client(
        [write("package.json", BROKEN), text("done")], executor=ScriptedExecutor([PASS])
    )
    cid, run_id = begin(
        client, project_dir, check_command="python check.py", check_kinds={"config": False}
    )
    rows = texts(wait_run(client, cid, run_id))
    assert "Not checked: config files switched off for this project" in rows, rows
    assert not any(one.startswith("package.json") for one in rows), rows


def test_unended_strings_and_comments_are_read_in_one_pass(tmp_path):
    # (Each unended one read again from every later quote took time squared: a 600 KB file
    # held the check for minutes - now well under a second.)
    from tests.conftest import scaled

    hostile = {
        "a.json": '{"a": "' + '\\"' * 200_000,
        "b.json": "{" + "/*a" * 200_000,
        "c.toml": 'a = """' + "'''b" * 100_000,
    }
    started = time.monotonic()
    rows = said(tmp_path, hostile)
    assert time.monotonic() - started < scaled(5), rows
    assert [state for state, _text in rows] == ["failed", "failed", "failed"], rows
