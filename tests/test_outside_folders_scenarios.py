"""Slice 41's acceptance set: folders outside the project, as the CLIs have them. Written before
the code.

A project can be given more folders to work in (`also_in`); there the tools work as in the
project, under the same permission level. A folder the user names in their own message is
opened to read for that conversation, with no card (B-52); one named by anybody else is not. Any other path
outside the project is asked for - at Full auto too - once, or for its whole folder, or not at
all. The user's secrets, the system's folders, the drive's and the home folder's roots are never
opened, by whatever name or link. Claude Code is given the folders with --add-dir.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.schemas import ProjectOut

if "also_in" not in ProjectOut.model_fields:  # written before the code: skipped until it exists
    pytest.skip("slice 41 is not built yet", allow_module_level=True)

from app.workspace import never  # noqa: E402
from tests.fakes import Script, ScriptedExecutor  # noqa: E402
from tests.test_agent_commands import cmd  # noqa: E402
from tests.test_agent_writes import wait_status, write  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_claude_native import claude_app  # noqa: E402, F401  (a fixture)
from tests.test_spawn import call, step  # noqa: E402

ORIGIN = "http://127.0.0.1:8790"
HOME = Path.home()
NEVER = [
    HOME / ".ssh", HOME / ".SSH", HOME / "x" / ".." / ".codex", HOME / ".claude", HOME / ".aws",
    HOME, Path(HOME.anchor), Path("C:/Windows"), Path("C:/Program Files"), Path("C:/PROGRA~1"),
]


def read(path, id="r"):
    return step(call("read_file", {"path": str(path)}, id))


def project(client, project_dir, **patch):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    if patch:
        patched = client.patch(f"/api/projects/{pid}", json=patch, headers={"Origin": ORIGIN})
        assert patched.status_code == 200, patched.text
    return pid


def converse(client, pid, mode="ask", content="go on"):
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": mode},
                 headers={"Origin": ORIGIN})
    # (From the app's own page: since slice 75 only there does a folder it names open.)
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": content},
                      headers={"Origin": ORIGIN}).json()
    return cid, run["run"]["id"]


def conversation(client, cid):
    return client.get(f"/api/conversations/{cid}").json()["conversation"]


@pytest.fixture
def other(tmp_path):
    """A folder outside the project, with a file in it."""
    folder = tmp_path / "other"
    folder.mkdir()
    (folder / "notes.md").write_text("other notes\n", encoding="utf-8")
    return folder


# --- the project's list ------------------------------------------------------------------------


def test_in_a_folder_of_the_projects_list_the_tools_work_as_in_the_project(
    make_client, wait_run, project_dir, other
):
    client, _model = make_client([
        read(other / "notes.md"),
        write(str(other / "out.md"), "written\n", id="w"), text("done")])
    pid = project(client, project_dir, also_in=[str(other)])
    assert client.get(f"/api/projects/{pid}").json()["also_in"] == [str(other)]
    cid, run_id = converse(client, pid, mode="auto_edit")
    snap = wait_run(client, cid, run_id)
    first, second = snap["tool_calls"]
    assert first["status"] == "succeeded" and "other notes" in first["result"]
    assert second["status"] == "succeeded", second["result"]
    assert (other / "out.md").read_text(encoding="utf-8") == "written\n"
    # on record by where it truly is
    (change,) = snap["file_changes"]
    assert Path(change["path"]) == other / "out.md" and change["status"] == "applied"


def test_a_write_there_still_waits_at_ask(make_client, project_dir, other):
    client, _model = make_client([write(str(other / "out.md"), "x\n"), text("ok")])
    pid = project(client, project_dir, also_in=[str(other)])
    cid, _run_id = converse(client, pid, mode="ask")
    snap = wait_status(client, cid, "waiting_approval")
    assert snap["file_changes"][0]["status"] == "proposed"
    assert not (other / "out.md").exists()
    assert [t["status"] for t in snap["tool_calls"] if t["status"] == "pending"] == []


def test_a_command_runs_in_a_folder_of_the_list(make_client, wait_run, project_dir, other):
    executor = ScriptedExecutor([Script(["ok\n"], exit_code=0)])
    client, _model = make_client([cmd("dir", cwd=str(other)), text("ran")], executor=executor)
    pid = project(client, project_dir, also_in=[str(other)])
    cid, run_id = converse(client, pid, mode="full_auto")
    wait_run(client, cid, run_id)
    assert [(c, Path(where)) for c, where in executor.started] == [("dir", other)]


@pytest.mark.parametrize("never", NEVER, ids=str)
def test_the_list_never_takes_a_secret_or_system_folder(make_client, project_dir, never):
    client, _model = make_client([])
    pid = project(client, project_dir)
    refused = client.patch(f"/api/projects/{pid}", json={"also_in": [str(never)]},
                           headers={"Origin": ORIGIN})
    assert refused.status_code == 422, (never, refused.text)


@pytest.mark.parametrize("name", [".qoder", ".kaggle", ".docker", ".azure",
                                  ".databricks", ".cline", ".continue", ".lmstudio",  # (B-65)
                                  ".ollama", ".qoder-cli", ".qodersec", ".lingma", ".cagent",
                                  ".claude-server-commander"])  # (B-94)
def test_other_clis_and_clouds_homes_are_never_opened(name):
    # (seen live, 24 Oct: B-47; KOLONİ itself reads none of them through these rules)
    assert never(HOME / name / "x.json") == "it holds the user's settings and secrets"


@pytest.mark.parametrize("bad", ["relative/path", "\\\\host\\share", "MISSING"])
def test_the_list_takes_existing_absolute_local_folders_only(make_client, project_dir, tmp_path,
                                                             bad):
    client, _model = make_client([])
    pid = project(client, project_dir)
    bad = str(tmp_path / "missing") if bad == "MISSING" else bad
    refused = client.patch(f"/api/projects/{pid}", json={"also_in": [bad]},
                           headers={"Origin": ORIGIN})
    assert refused.status_code == 422


def test_the_list_is_changed_from_the_apps_own_page_only(make_client, project_dir, other):
    client, _model = make_client([])
    pid = project(client, project_dir)
    assert client.patch(f"/api/projects/{pid}", json={"also_in": [str(other)]}).status_code == 403


# --- the user's own message --------------------------------------------------------------------


def test_a_folder_the_user_names_is_opened_for_that_conversation_with_no_card(
    make_client, wait_run, project_dir, other
):
    client, _model = make_client([read(other / "notes.md"), text("read it")])
    pid = project(client, project_dir)
    cid, run_id = converse(client, pid, mode="ask",
                           content=f"Read {other / 'notes.md'} and tell me what it says")
    snap = wait_run(client, cid, run_id)
    assert snap["tool_calls"][0]["status"] == "succeeded"       # nobody was asked
    # The file's folder, to read in (B-52): a name in a message is no leave to change files.
    assert conversation(client, cid)["read_in"] == [str(other)]
    assert conversation(client, cid)["also_in"] == []
    # for that conversation only
    other_cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert conversation(client, other_cid)["read_in"] == []
    # and the user takes it back
    taken = client.patch(f"/api/conversations/{cid}", json={"read_in": []},
                         headers={"Origin": ORIGIN})
    assert taken.status_code == 200 and conversation(client, cid)["read_in"] == []


def test_a_write_in_a_folder_the_user_names_is_asked_at_full_auto_too(
    make_client, project_dir, other
):
    client, _model = make_client([write(str(other / "out.md"), "x\n"), text("ok")])
    pid = project(client, project_dir)
    cid, _run_id = converse(client, pid, mode="full_auto", content=f"list {other}")
    (tool,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    assert tool["status"] == "pending"
    assert not (other / "out.md").exists()
    assert conversation(client, cid)["read_in"] == [str(other)]
    assert conversation(client, cid)["also_in"] == []


def test_a_folder_the_user_names_that_the_chat_writes_in_already_stays_so(
    make_client, wait_run, project_dir, other
):
    client, _model = make_client([text("ok")])
    pid = project(client, project_dir, also_in=[str(other)])
    cid, run_id = converse(client, pid, content=f"list {other}")
    wait_run(client, cid, run_id)
    assert conversation(client, cid)["also_in"] == [str(other)]
    assert conversation(client, cid)["read_in"] == []


@pytest.mark.parametrize("kept", [False, True], ids=["named now", "kept from before"])
def test_the_project_named_by_the_user_is_not_one_of_its_own_folders(
    make_client, wait_run, project_dir, kept
):
    """B-66: listed as one to read in, a copy's command naming the project was offered
    "Allow changes in this folder: <the project>". It is asked as one that names the
    project from a copy (`copy_reason`): a command's card, no folder's - also where a
    chat's list holds the project from before."""
    (project_dir / "src").mkdir()
    named = f"type {project_dir / 'hello.py'}"
    client, _model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Coder", "task": "do it"}, "s")),
                 text("done")],
        "Coder": [step(call("run_command", {"command": named}, "c")), text("A done")]})
    pid = project(client, project_dir)
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "full_auto", "spawn_approval": "never"}, headers={"Origin": ORIGIN})
    if kept:  # (put on the list before B-93, when it could be: no request lists it now)
        from app.db.models import Conversation

        with client.app.state.session_factory() as session:
            session.get_one(Conversation, cid).read_in = [str(project_dir)]
            session.commit()
    client.post(f"/api/conversations/{cid}/messages", headers={"Origin": ORIGIN}, json={
        "content": "go on" if kept else f"{named} and look in {project_dir / 'src'}"})
    assert conversation(client, cid)["read_in"] == ([str(project_dir)] if kept else [])
    snap = wait_status(client, cid, "waiting_approval")
    assert [(c["command"], c["status"]) for c in snap["commands"]] == [(named, "proposed")]
    assert snap["questions"] == []
    # Its card says why it is asked (B-99's Test-Path card said nothing).
    (asked,) = [t for t in snap["tool_calls"] if t["name"] == "run_command"]
    assert asked["status"] == "running" and asked["why_asked"].startswith(
        f"it names the project folder ({project_dir})")
    client.post(f"/api/commands/{snap['commands'][0]['id']}/reject", headers={"Origin": ORIGIN})


def test_a_path_named_by_anybody_but_the_user_opens_nothing(
    make_client, wait_run, project_dir, other
):
    (project_dir / "README.md").write_text(f"See {other} for more.\n", encoding="utf-8")
    client, _model = make_client([
        step(call("read_file", {"path": "README.md"}, "r1"), content=f"I will look in {other}"),
        read(other / "notes.md", "r2"), text("ok")])
    pid = project(client, project_dir)
    cid, _run_id = converse(client, pid, mode="full_auto", content="read the readme")
    snap = wait_status(client, cid, "waiting_approval")      # asked, at Full auto too
    assert conversation(client, cid)["also_in"] == []
    assert snap["tool_calls"][-1]["status"] == "pending"


# (~/.codex is a CLI's own folder since K-ev-klasoru: a file there is a card - tests/test_cli_home.py)
@pytest.mark.parametrize("never", NEVER[:2], ids=str)
def test_a_secret_folder_named_by_the_user_is_not_opened(make_client, wait_run, project_dir,
                                                         never):
    client, _model = make_client([read(never / "koloni-test-none"), text("ok")])
    pid = project(client, project_dir)
    cid, run_id = converse(client, pid, mode="full_auto", content=f"read {never / 'koloni-test-none'}")
    snap = wait_run(client, cid, run_id)
    assert conversation(client, cid)["also_in"] == []
    (tool,) = snap["tool_calls"]
    assert tool["status"] == "failed"                         # refused outright, nobody asked


# --- any other path: asked -----------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["ask", "full_auto"])
def test_another_path_outside_is_asked_for_at_every_level(make_client, project_dir, other, mode):
    client, _model = make_client([read(other / "notes.md"), text("ok")])
    pid = project(client, project_dir)
    cid, _run_id = converse(client, pid, mode=mode)
    snap = wait_status(client, cid, "waiting_approval")
    (tool,) = snap["tool_calls"]
    assert tool["status"] == "pending" and other.name in json.dumps(tool)


def test_allowed_once_it_is_asked_for_again_next_time(make_client, wait_run, project_dir, other):
    client, _model = make_client([read(other / "notes.md", "r1"),
                                  read(other / "notes.md", "r2"), text("ok")])
    pid = project(client, project_dir)
    cid, run_id = converse(client, pid, mode="full_auto")
    first = wait_status(client, cid, "waiting_approval")["tool_calls"][0]
    once = client.post(f"/api/tool-calls/{first['id']}/approve", json={"scope": "once"},
                       headers={"Origin": ORIGIN})
    assert once.status_code == 200, once.text
    snap = wait_status(client, cid, "waiting_approval")      # the second read asks again
    assert [t["status"] for t in snap["tool_calls"]] == ["succeeded", "pending"]
    assert conversation(client, cid)["also_in"] == []
    client.post(f"/api/tool-calls/{snap['tool_calls'][1]['id']}/reject", headers={"Origin": ORIGIN})
    snap = wait_run(client, cid, run_id)
    assert snap["tool_calls"][1]["status"] == "denied"


def test_allowed_for_its_folder_it_is_not_asked_for_again(make_client, wait_run, project_dir,
                                                         other):
    client, _model = make_client([read(other / "notes.md", "r1"),
                                  read(other / "notes.md", "r2"), text("ok")])
    pid = project(client, project_dir)
    cid, run_id = converse(client, pid, mode="full_auto")
    first = wait_status(client, cid, "waiting_approval")["tool_calls"][0]
    assert client.post(f"/api/tool-calls/{first['id']}/approve", json={"scope": "folder"},
                       headers={"Origin": ORIGIN}).status_code == 200
    snap = wait_run(client, cid, run_id)
    assert [t["status"] for t in snap["tool_calls"]] == ["succeeded", "succeeded"]
    # (A read's card opens the folder to read in, since slice 75: never to change files.)
    assert conversation(client, cid)["read_in"] == [str(other)]


def junction(link, target):
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                          capture_output=True, text=True)
    if made.returncode != 0:
        pytest.skip(f"no junctions here: {made.stderr}")


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows'")
def test_a_link_inside_a_listed_folder_does_not_lead_past_the_list(
    make_client, project_dir, other, tmp_path
):
    beyond = tmp_path / "beyond"
    beyond.mkdir()
    (beyond / "secret.md").write_text("beyond\n", encoding="utf-8")
    junction(other / "door", beyond)
    client, _model = make_client([read(other / "door" / "secret.md"), text("ok")])
    pid = project(client, project_dir, also_in=[str(other)])
    cid, _run_id = converse(client, pid, mode="full_auto")
    snap = wait_status(client, cid, "waiting_approval")      # it is where the link leads
    (tool,) = snap["tool_calls"]
    assert tool["status"] == "pending" and "beyond" not in (tool["result"] or "")


@pytest.mark.parametrize("path", ["\\\\127.0.0.1\\c$\\Windows\\win.ini",
                                  str(HOME / ".ssh" / "koloni-test-none")])
def test_a_network_path_or_a_secret_is_refused_without_asking(make_client, wait_run,
                                                               project_dir, path):
    client, _model = make_client([read(path), text("ok")])
    pid = project(client, project_dir)
    cid, run_id = converse(client, pid, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    (tool,) = snap["tool_calls"]
    assert tool["status"] == "failed"


# --- Claude Code -------------------------------------------------------------------------------


def test_claude_code_is_given_the_folders_with_add_dir(
    claude_app, wait_run, project_dir, other  # noqa: F811
):
    client, provider, _ = claude_app([{"say": "Looked."}], model="claude-sonnet-5-5")
    pid = project(client, project_dir, also_in=[str(other)])
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={
        "permission_mode": "ask", "provider_id": provider["id"]}, headers={"Origin": ORIGIN})
    run = client.post(f"/api/conversations/{cid}/messages", json={"content": "look"}).json()
    wait_run(client, cid, run["run"]["id"])
    argv = claude_app.record()["argv"]
    given = [argv[i + 1] for i, word in enumerate(argv) if word == "--add-dir"]
    assert str(other) in given

