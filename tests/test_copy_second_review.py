"""Working copies after the review of slice 19c as it was completed: what a card of a copy
with nothing to say what it was made from may offer, how such a copy's layout is known, and
that a file named like a folder a copy leaves out is a file like any other.
"""

import shutil

import pytest
from sqlalchemy import select

from app import copies
from app.config import load_settings
from app.db.models import Agent, Merge
from app.db.session import make_engine, make_session_factory, upgrade_db
from app.main import create_app
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_claim_scenarios import agent, calls, write
from tests.test_copy_later_scenarios import again, interrupted
from tests.test_copy_runner import (
    ORIGIN,
    a_change,
    an_agent,
    at_work,
    card_of,
    edit,
    kept_folders,
    on_record,
)
from tests.test_copy_scenarios import files, one
from tests.test_spawn import step

# --- a card of a copy with nothing to say what it was made from ---------------------------------


def test_a_copy_without_its_base_does_not_offer_to_put_back_what_the_user_changed_since(
    settings_env, project_dir
):
    """Its base was deleted (a command of the agent's can do that) and the user worked on:
    one Apply put the old `hello.py` back beside the agent's `a.txt`."""
    (project_dir / "other.py").write_text("one\n", encoding="utf-8")
    cid = at_work(settings_env, project_dir, [
        step(write("a.txt", "A")), step(edit("other.py", "one", "the agent's", "e"))])
    (folder,) = kept_folders(settings_env)
    (folder / copies.BASE_FILE).unlink()
    (folder / "tree" / "made.txt").write_text("by a command", encoding="utf-8")
    (project_dir / "hello.py").write_text("print('the user, later')\n", encoding="utf-8")
    (project_dir / "more.py").write_text("the user's new file\n", encoding="utf-8")
    with again(settings_env) as client:
        card = card_of(client, cid)
        # what the agent is on record with, and what the project does not have at all
        assert files(card) == {"a.txt": "conflict", "hello.py": "left_out",
                               "made.txt": "conflict", "other.py": "conflict"}
        left = card["files"][1]
        assert left["diff"] is None and "what this copy started from is not known" in left["note"]
        said = client.post(f"/api/merges/{card['id']}/approve")
        assert said.status_code == 200
        assert files(said.json()) == {"a.txt": "applied", "hello.py": "left_out",
                                      "made.txt": "applied", "other.py": "applied"}
        assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('the user, later')\n"
        assert (project_dir / "more.py").is_file()          # not in the copy: not deleted
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
        assert (project_dir / "other.py").read_text(encoding="utf-8") == "the agent's\n"
        assert (project_dir / "made.txt").read_text(encoding="utf-8") == "by a command"
        # The copy's own `hello.py` was never offered, and is nowhere else: the folder
        # stays until the user says Discard - Apply took what it showed, no more.
        assert said.json()["status"] == "kept"
        assert (folder / "tree" / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 409
    with again(settings_env) as client:                     # and after another start
        card = card_of(client, cid)
        assert files(card)["hello.py"] == "left_out" and files(card)["a.txt"] == "applied"
        said = client.post(f"/api/merges/{card['id']}/reject")
        assert said.status_code == 200 and kept_folders(settings_env) == []
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"


def test_a_copy_that_only_differs_where_nothing_is_on_record_is_kept_and_only_to_discard(
    settings_env, project_dir
):
    """Nothing of it is offered - and nothing of it is thrown away unasked either."""
    cid = at_work(settings_env, project_dir, [step(write("a.txt", "A"))])
    (folder,) = kept_folders(settings_env)
    (folder / copies.BASE_FILE).unlink()
    (folder / "tree" / "a.txt").unlink()
    (folder / "tree" / "hello.py").write_text("print('a command did this')\n", encoding="utf-8")
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert card["status"] == "kept" and files(card) == {"hello.py": "left_out"}
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 409
        assert (folder / "tree" / "hello.py").is_file()
        assert (project_dir / "hello.py").read_text(encoding="utf-8") == "print('hi')\n"
        assert client.post(f"/api/merges/{card['id']}/reject").status_code == 200
        assert kept_folders(settings_env) == []


# --- how a kept copy is laid out is what the records say, not what its folder holds -------------


def kept_before(tmp_path, settings, kept_in, tree=None):
    """A kept copy `x` of slice 19b's layout - the folder itself is the copy - whose only
    entry is the project's folder `tree`; on record as kept in `kept_in`."""
    upgrade_db(settings.db_path)
    factory = make_session_factory(make_engine(settings.db_path))
    project = tmp_path / "proj"
    (project / "tree" / "src").mkdir(parents=True)
    (project / "tree" / "src" / "x.py").write_text("old\n", encoding="utf-8")
    folder = settings.runtime_root / "copies" / "x"
    shutil.copytree(project, folder)
    (folder / "tree" / "src" / "x.py").write_text("A", encoding="utf-8")   # as its record has it
    with factory() as s:
        on_record(s, project)
        an_agent(s, "x")
        if tree:
            s.get_one(Agent, "x").copy = {"state": "own", "tree": tree(folder)}
        a_change(s, "f1", "x", "tree/src/x.py", kind="modify")
        if kept_in:
            s.add(Merge(id="m1", run_id="r", agent_id="x", status="interrupted", files=[],
                        kept_in=kept_in(folder)))
        s.commit()
    return factory, project, folder


def test_a_copy_of_the_layout_before_trees_whose_only_entry_is_a_folder_named_tree(
    tmp_path, settings
):
    """It was taken for the new layout: the project's tree/src/x.py was offered as src/x.py."""
    factory, project, folder = kept_before(tmp_path, settings, str)
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = ORIGIN
        with factory() as s:
            (merge,) = s.scalars(select(Merge)).all()
            assert [(f["path"], f["state"]) for f in merge.files] == [
                ("tree/src/x.py", "conflict")]
            assert merge.kept_in == str(folder)
        assert client.post("/api/merges/m1/approve").status_code == 200
    assert (project / "tree" / "src" / "x.py").read_text(encoding="utf-8") == "A"
    assert not (project / "src").exists() and not folder.exists()


def test_a_copy_with_a_tree_whose_base_is_gone_is_not_the_older_layout_for_a_file_beside_it(
    settings_env, project_dir
):
    """It was: `tree/a.txt` and `tree/hello.py` were offered as new files of the project."""
    cid = interrupted(settings_env, project_dir)
    (folder,) = kept_folders(settings_env)
    (folder / copies.BASE_FILE).unlink()
    (folder / "notes.txt").write_text("left by a command", encoding="utf-8")
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert card["kept_in"] == str(folder / "tree") and files(card) == {"a.txt": "conflict"}
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
        assert (project_dir / "a.txt").read_text(encoding="utf-8") == "A"
        assert not (project_dir / "tree").exists() and not (project_dir / "notes.txt").exists()


def test_a_copy_made_now_is_on_record_with_its_tree_before_anything_is_kept(
    settings_env, project_dir
):
    """Killed while its agent was at work: no card had been put on record yet."""
    cid = at_work(settings_env, project_dir, [step(write("a.txt", "A"))])
    (folder,) = kept_folders(settings_env)
    with make_session_factory(make_engine(load_settings(settings_env).db_path))() as s:
        assert [a.copy for a in s.scalars(select(Agent)) if a.copy] == [
            {"state": "own", "tree": str(folder / "tree")}]
        for merge in s.scalars(select(Merge)):          # as a kill would have left it
            s.delete(merge)
        s.commit()
    (folder / copies.BASE_FILE).unlink()
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert card["kept_in"] == str(folder / "tree") and files(card) == {"a.txt": "conflict"}
        # what the API says of the agent is as before
        snap = client.get(f"/api/conversations/{cid}").json()
        assert agent(snap, "Coder")["copy"] == {"state": "own"}


@pytest.mark.parametrize("layout", ["tree", "folder"])
def test_a_base_less_copy_no_record_says_the_layout_of_is_only_to_discard_and_stays_so(
    tmp_path, settings, layout
):
    factory, project, folder = kept_before(tmp_path, settings, None)
    if layout == "tree":            # as slice 19c lays a copy out, its base gone
        (folder / "tree" / "tree").mkdir()
        shutil.move(str(folder / "tree" / "src"), str(folder / "tree" / "tree" / "src"))
    for _restart in range(2):
        with TestClient(create_app(settings), base_url="http://127.0.0.1:8790") as client:
            client.headers["Origin"] = ORIGIN
            with factory() as s:
                (merge,) = s.scalars(select(Merge)).all()
                assert merge.status == "interrupted"
                assert [(f["path"], f["state"]) for f in merge.files] == [
                    ("tree/src/x.py", "refused")]
                merge_id = merge.id
            assert client.post(f"/api/merges/{merge_id}/approve").status_code == 409
            assert (project / "tree" / "src" / "x.py").read_text(encoding="utf-8") == "old\n"
            assert not (project / "src").exists() and folder.is_dir()
    with TestClient(create_app(settings), base_url="http://127.0.0.1:8790") as client:
        client.headers["Origin"] = ORIGIN
        assert client.post(f"/api/merges/{merge_id}/reject").status_code == 200
        assert not folder.exists()


# --- a file named like a folder a copy leaves out ------------------------------------------------


def test_a_file_named_like_a_folder_a_copy_leaves_out_is_copied_and_taken_back(
    tmp_path, project_dir
):
    """A `./build` script, a Bazel `BUILD` file: they were not in the copy at all, and an
    agent's change to one was dropped without a word."""
    (project_dir / "build").write_text("#!/bin/sh\n", encoding="utf-8")
    (project_dir / "pkg").mkdir()
    (project_dir / "pkg" / "BUILD").write_text("bazel\n", encoding="utf-8")
    (project_dir / "venv").write_text("a file, not an environment", encoding="utf-8")
    (project_dir / "dist").mkdir()
    (project_dir / "dist" / "out.js").write_text("built", encoding="utf-8")
    (project_dir / "sub" / "node_modules").mkdir(parents=True)
    made = copies.make(project_dir, tmp_path / "runtime", "a1")
    assert (made.root / "build").is_file() and (made.root / "pkg" / "BUILD").is_file()
    assert (made.root / "venv").is_file() and not (made.root / "dist").exists()
    assert list(made.links) == ["sub/node_modules"]
    (made.root / "build").write_text("#!/bin/sh\nmake\n", encoding="utf-8")
    (made.root / "pkg" / "BUILD").unlink()
    (made.root / "pkg" / "dist").write_text("a new file of that name", encoding="utf-8")
    (made.root / "dist").mkdir()
    (made.root / "dist" / "new.js").write_text("built in the copy", encoding="utf-8")
    wanted = [("build", "changed", "ready"), ("pkg/BUILD", "deleted", "ready"),
              ("pkg/dist", "new", "ready")]
    assert made.changes() == wanted
    copies.unlink(tmp_path / "runtime", "a1")
    assert copies.load(project_dir, tmp_path / "runtime", "a1").changes() == wanted
    # the project's file changed meanwhile: the copy that had not changed it gets it
    (project_dir / "venv").write_text("another", encoding="utf-8")
    assert made.refresh("venv") and (made.root / "venv").read_text(encoding="utf-8") == "another"


def test_gits_own_is_left_out_of_a_copy_also_where_it_is_a_file(tmp_path, project_dir):
    """A worktree's `.git` is a file that names the repository: git in the copy would
    work on that."""
    (project_dir / ".git").write_text("gitdir: /somewhere/else\n", encoding="utf-8")
    made = copies.make(project_dir, tmp_path / "runtime", "a1")
    assert not (made.root / ".git").exists()
    (made.root / ".git").write_text("gitdir: /the/agents/own\n", encoding="utf-8")
    assert made.changes() == []


def test_an_agent_changes_a_file_named_build_in_its_copy_and_the_project_gets_it(
    make_client, wait_run, project_dir
):
    (project_dir / "build").write_text("old\n", encoding="utf-8")
    client, model, cid, run_id = one(make_client, project_dir, [
        step(write("build", "new\n")), step(write("dist./out.js", "x", "w2")),
        step(write("sub/Build/out.js", "x", "w3")), text("A done")])
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    wrote, dotted, under = calls(snap, "Coder", "write_file")
    assert wrote[0] == "succeeded"
    # (Windows drops the dot at the end of a folder's name: it is the folder `dist`)
    assert dotted[0] == "failed" and "not part of a working copy" in dotted[1]
    assert under[0] == "failed" and "not part of a working copy" in under[1]
    assert (project_dir / "build").read_text(encoding="utf-8") == "new\n"
    assert not (project_dir / "dist").exists() and not (project_dir / "sub").exists()
