"""R161: what a command makes - a docx, a pdf, a picture, which only a command can write - is the
agent's output beside the chat, as a file it wrote with write_file is: listed with its agent.
Not a note (.md), nothing in `.koloni/`, and not a file that was there before."""

from app import views as views_module
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_commands import cmd
from tests.test_chat_flow import start_in_mode, text
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_native_agent import start as start_native
from tests.test_spawn import call, step
from tests.test_view_scenarios import content, views


def made(client, cid):
    return {v["path"]: v for v in views(client, cid)}


def test_a_document_a_command_makes_is_its_agents_output(make_client, wait_run, project_dir):
    (project_dir / "old.pdf").write_bytes(b"%PDF-1.4 before")
    executor = ScriptedExecutor([Script(["ok\n"], writes={
        "docs/note.docx": "PK docx", "docs/note.md": "# a note", ".koloni/tmp/out.docx": "PK",
        "chart.png": "png"})])
    client, _model = make_client([cmd("python make_docs.py"), text("Made them.")],
                                 executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    agent_id = snap["agents"][0]["id"]
    listed = made(client, cid)
    assert sorted(listed) == ["chart.png", "docs/note.docx"]
    assert {v["agent_id"] for v in listed.values()} == {agent_id}
    assert listed["docs/note.docx"]["kind"] == "docx"
    assert content(client, listed["chart.png"]).content == b"png"


def test_in_a_copy_only_what_the_command_made_there_is_listed(make_client, wait_run, project_dir):
    # The first command makes the sub-agent's copy: every file in it is new on disk, yet only
    # the one the command wrote is its.
    (project_dir / "old.pdf").write_bytes(b"%PDF-1.4 before")
    executor = ScriptedExecutor([Script(["ok\n"], writes={"report.pdf": "%PDF-1.4 new"})])
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "make the report"}, "s")),
                 text("done")],
        "Coder": [step(call("run_command", {"command": "python report.py"}, "k")),
                  text("made it")],
    }, executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    snap = wait_run(client, cid, run_id, timeout=15)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    coder = next(a["id"] for a in snap["agents"] if a["role_name"] == "Coder")
    listed = made(client, cid)
    assert list(listed) == ["report.pdf"] and listed["report.pdf"]["agent_id"] == coder
    assert content(client, listed["report.pdf"]).content == b"%PDF-1.4 new"


def test_a_document_a_clis_command_makes_is_its_output(native_app, wait_run, project_dir):  # noqa: F811
    # (Too large to be kept as text: as a binary docx is, it gets no change record.)
    big = "x" * 300_000
    client, provider, _ = native_app([
        {"run": "python make_docx.py", "touches": {"docs/rea-note.docx": big,
                                                   ".koloni/tmp/out.pdf": big}},
        {"say": "Made it."}])
    cid, run_id = start_native(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    listed = made(client, cid)
    assert list(listed) == ["docs/rea-note.docx"]
    assert listed["docs/rea-note.docx"]["agent_id"] == snap["agents"][0]["id"]


def test_an_agents_outputs_are_capped_and_a_coverage_report_is_not_looked_into(
        make_client, wait_run, project_dir, monkeypatch):
    monkeypatch.setattr(views_module, "MOST_MADE", 2)
    executor = ScriptedExecutor([
        Script(["ok\n"], writes={"a.png": "a", "b.png": "b", "htmlcov/index.html": "<p>"}),
        Script(["ok\n"], writes={"c.png": "c"})])
    client, _model = make_client([cmd("pytest --cov-report=html", "k1"),
                                  cmd("python plot.py", "k2"), text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    assert sorted(made(client, cid)) == ["a.png", "b.png"]  # (c.png: past the cap)


def test_a_known_output_made_again_is_not_checked_again(
        make_client, wait_run, project_dir, monkeypatch):
    checked = []
    real = views_module.check_shown
    monkeypatch.setattr(views_module, "check_shown",
                        lambda ws, path: checked.append(path) or real(ws, path))
    executor = ScriptedExecutor([Script(["ok\n"], writes={"r.pdf": "one"}),
                                 Script(["ok\n"], writes={"r.pdf": "two"})])
    client, _model = make_client([cmd("python r.py", "k1"), cmd("python r.py", "k2"),
                                  text("done")], executor=executor)
    cid, run_id = start_in_mode(client, project_dir, "full_auto")
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    assert list(made(client, cid)) == ["r.pdf"] and checked == ["r.pdf"]


def test_the_look_after_a_command_walks_a_bounded_part_of_the_project(tmp_path, monkeypatch):
    for n in range(5):
        (tmp_path / "out").mkdir(exist_ok=True)
        (tmp_path / "out" / f"{n}.png").write_bytes(b"x")
    (tmp_path / "Node_Modules").mkdir()
    (tmp_path / "Node_Modules" / "logo.png").write_bytes(b"x")
    assert sorted(views_module.made_since(tmp_path, 0)) == [f"out/{n}.png" for n in range(5)]
    monkeypatch.setattr(views_module, "MOST_MADE", 3)
    assert len(views_module.made_since(tmp_path, 0)) == 3
    monkeypatch.setattr(views_module, "MOST_WALKED", 2)  # (past it in out/: not looked at)
    assert views_module.made_since(tmp_path, 0) == []
