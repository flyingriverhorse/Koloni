"""A turn nobody watched - a trigger's, before 0.1.10 - may have left a kept copy that outlives the
upgrade: its run says so (`runs.unattended`), and Take in still holds it to what such a turn never
writes; its commit is offered on the user's own Apply. The run is marked so in the database, as an
old trigger turn's is."""

import sqlite3

from app.config import load_settings
from tests.test_claim_scenarios import write
from tests.test_copy_later_scenarios import again
from tests.test_copy_runner import at_work, card_of, kept_folders
from tests.test_copy_scenarios import files
from tests.test_spawn import step
from tests.test_take_in_scenarios import LINES, needs_git, repository
from tests.test_take_in_scenarios import git as in_repo


def nobody_watched(settings_env, cid):
    """The chat's turn on record as one nobody watched - a trigger's turn from before 0.1.10, whose
    kept copy outlives the upgrade: its run as such a turn left it."""
    with sqlite3.connect(load_settings(settings_env).db_path) as conn:
        changed = conn.execute(
            "UPDATE runs SET unattended = 1, trigger_id = 'gone', trigger_name = 'Nightly' "
            "WHERE conversation_id = ?",
            (cid,),
        ).rowcount
    assert changed == 1


def test_after_a_restart_a_turn_nobody_watched_still_does_not_get_its_protected_paths(
    settings_env, project_dir
):
    cid = at_work(settings_env, project_dir, [step(write("notes.txt", "seen"))])
    nobody_watched(settings_env, cid)
    (folder,) = kept_folders(settings_env)
    (folder / "tree" / ".claude").mkdir()  # as a command of its would have made it
    (folder / "tree" / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    with again(settings_env) as client:
        card = card_of(client, cid)
        assert files(card) == {".claude/settings.json": "refused", "notes.txt": "ready"}
        assert "no trigger allows" in card["files"][0]["note"]
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
        assert (project_dir / "notes.txt").read_text(encoding="utf-8") == "seen"
        assert not (project_dir / ".claude").exists()
        # what was refused is nowhere but in the copy: it stays until Discard
        assert card_of(client, cid)["status"] == "kept"
        assert (folder / "tree" / ".claude" / "settings.json").is_file()


@needs_git
def test_a_copy_a_turn_nobody_watched_kept_is_offered_its_commit_once_the_user_takes_it(
    settings_env, project_dir
):
    """A copy kept by a turn nobody watched (a trigger's, before 0.1.10) is the user's own Apply:
    its commit is offered then - none is made."""
    (project_dir / "lines.txt").write_bytes(LINES.encode())
    repository(project_dir)
    cid = at_work(settings_env, project_dir, [step(write("a.txt", "A"))])
    nobody_watched(settings_env, cid)
    with again(settings_env) as client:
        pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
        patched = client.patch(f"/api/projects/{pid}", json={"git_commit": True})
        assert patched.status_code == 200, patched.text
        card = card_of(client, cid)
        assert client.post(f"/api/merges/{card['id']}/approve").status_code == 200
        (merge,) = client.get(f"/api/conversations/{cid}").json()["merges"]
        assert merge["status"] == "applied" and merge["commit"]["state"] == "offered"
    assert in_repo(project_dir, "log", "--format=%s") == "as it was"
