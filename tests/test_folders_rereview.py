"""Slice 75's re-review, made tests: the most specific list wins, a listed folder may hold only
KOLONİ's own places, a command names a folder by its whole name, the secrets known by name, and
slice 41's own way of opening a folder to changes."""

import pytest

from app.workspace import Workspace, WorkspaceError, is_secret
from tests.test_agent_commands import cmd
from tests.test_agent_writes import wait_status, write
from tests.test_chat_flow import text
from tests.test_folders import ORIGIN, lists, native, start
from tests.test_native_agent import native_app  # noqa: F401  (a fixture)
from tests.test_outside_folders_scenarios import conversation, project, read


@pytest.fixture
def work(tmp_path):
    """A folder to write in holding one to read in only."""
    ro = tmp_path / "work" / "ro"
    ro.mkdir(parents=True)
    (tmp_path / "work" / "n.txt").write_text("n\n", encoding="utf-8")
    return tmp_path / "work"


# --- the most specific list wins -----------------------------------------------------------------


def test_naming_the_parent_of_a_folder_to_read_in_does_not_open_it_to_changes(
    make_client, wait_run, project_dir, work
):
    client, _model = make_client([text("ok"), write(str(work / "ro" / "out.md"), "x\n"),
                                  text("ok")])
    pid = project(client, project_dir, read_in=[str(work / "ro")])
    cid, run_id = start(client, pid, mode="full_auto")
    wait_run(client, cid, run_id)
    client.post(f"/api/conversations/{cid}/messages",
                json={"content": f"look at {work / 'n.txt'}"}, headers=ORIGIN)
    snap = wait_status(client, cid, "waiting_approval")       # at Full auto too
    # (Named, it is one to read in since B-52: no folder is opened to changes by a name.)
    assert conversation(client, cid)["read_in"] == [str(work / "ro"), str(work)]
    assert conversation(client, cid)["also_in"] == []
    assert snap["tool_calls"][-1]["status"] == "pending"
    assert not (work / "ro" / "out.md").exists()


def test_a_folder_to_write_in_does_not_open_one_to_read_in_inside_it(
    make_client, project_dir, work
):
    client, _model = make_client([write(str(work / "ro" / "out.md"), "x\n"), text("ok")])
    pid = project(client, project_dir, also_in=[str(work)], read_in=[str(work / "ro")])
    cid, _run_id = start(client, pid, mode="full_auto")
    (asked,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    assert asked["status"] == "pending" and asked["outside_folder"] == str(work / "ro")
    assert not (work / "ro" / "out.md").exists()


def test_no_cli_is_given_a_folder_to_write_in_that_holds_one_to_read_in(
    native_app, wait_run, project_dir, work, tmp_path  # noqa: F811
):
    other = tmp_path / "other"
    other.mkdir()
    client, provider, _ = native_app([{"say": "Looked."}])
    cid, run_id = native(client, provider, project_dir, "full_auto",
                         also_in=[str(work), str(other)], read_in=[str(work / "ro")])
    wait_run(client, cid, run_id)
    # (its folders to write in are its sandbox's writable roots: turn/start, slice 89a)
    assert native_app.record()["turn"]["sandboxPolicy"]["writableRoots"] == [str(other)]


# --- a listed folder holds only KOLONİ's own places ---------------------------------------------


def test_a_folder_holding_the_users_own_places_is_listed_nowhere(client, project_dir, tmp_path,
                                                                monkeypatch):
    roaming = tmp_path / "AppData" / "Roaming"
    (roaming / "agent-grid").mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(roaming))
    for holder in (roaming, roaming.parent):
        refused = lists(client, project_dir, read_in=[str(holder)])
        assert refused.status_code == 422 and "agent-grid" in refused.text


# --- a command names a folder by its whole name --------------------------------------------------


def test_a_command_naming_a_folder_beside_one_to_read_in_is_not_asked_for(
    make_client, wait_run, project_dir, tmp_path
):
    ro, robots = tmp_path / "ro", tmp_path / "robots"
    ro.mkdir()
    robots.mkdir()
    client, _model = make_client([cmd(f"dir {robots}"), text("ok")])
    pid = project(client, project_dir, read_in=[str(ro)])
    cid, run_id = start(client, pid, mode="full_auto")
    (ran,) = wait_run(client, cid, run_id)["tool_calls"]
    assert ran["status"] != "pending" and ran["outside_folder"] is None


# --- secrets by name -----------------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    ".env", ".ENV", "prod.env", "id_rsa", "key.pem", "credentials.json",
    "secrets.json", "secrets.yaml", "token.txt", "service-account-prod.json", "auth.json",
    ".htpasswd", "wallet.dat", "api_key.txt", "Login Data", "koloni.db", "koloni.db-wal",
    ".kube/config", ".docker/config.json", ".git/config",
    "gcloud/application_default_credentials.json", ".azure/accessTokens.json",
    ".env.", ".env ", ".env::$DATA",
])
def test_a_secret_in_a_listed_folder_is_never_opened(project_dir, tmp_path, name):
    shelf = tmp_path / "shelf"
    shelf.mkdir()
    assert is_secret(name)
    with pytest.raises(WorkspaceError, match="secret"):
        Workspace(project_dir, also=[shelf]).resolve(str(shelf / name))


def test_a_plain_file_in_a_listed_folder_is_not_taken_for_a_secret(project_dir, tmp_path):
    shelf = tmp_path / "shelf"
    shelf.mkdir()
    ws = Workspace(project_dir, also=[shelf])
    for name in ("notes.md", "config.toml", "tokens.ts", "docker-compose.yml"):
        assert ws.resolve(str(shelf / name)) == shelf / name


def test_a_path_with_a_nul_in_a_listed_folder_is_a_tool_error(make_client, wait_run,
                                                              project_dir, tmp_path):
    shelf = tmp_path / "shelf"
    shelf.mkdir()
    client, _model = make_client([read(str(shelf) + "\\a\x00b"), text("ok")])
    pid = project(client, project_dir, read_in=[str(shelf)])
    cid, run_id = start(client, pid, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    assert snap["tool_calls"][0]["status"] == "failed"


# --- slice 41's own way: a change's card opens its folder to changes -----------------------------


def test_allow_changes_in_this_folder_puts_it_on_the_list_to_write_in(make_client, wait_run,
                                                                      project_dir, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    client, _model = make_client([write(str(other / "a.md"), "a\n", id="w1"),
                                  write(str(other / "b.md"), "b\n", id="w2"), text("ok")])
    pid = project(client, project_dir)
    cid, run_id = start(client, pid, mode="full_auto")
    (asked,) = wait_status(client, cid, "waiting_approval")["tool_calls"]
    client.post(f"/api/tool-calls/{asked['id']}/approve", json={"scope": "folder"},
                headers=ORIGIN)
    snap = wait_run(client, cid, run_id)                     # the second is not asked for
    assert [t["status"] for t in snap["tool_calls"]] == ["succeeded", "succeeded"]
    assert conversation(client, cid)["also_in"] == [str(other)]
    assert (other / "b.md").read_text(encoding="utf-8") == "b\n"
