import pytest

from app.changes import ChangeConflict, apply_change, revert_change
from app.db.models import Agent, Conversation, FileChange, Message, Project, Run, ToolCall
from app.db.session import make_engine, make_session_factory, upgrade_db
from app.workspace import Workspace, WorkspaceError, sha256_text


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    db = tmp_path / "c.db"
    upgrade_db(db)
    session = make_session_factory(make_engine(db))()
    session.add(Project(id="p", name="p", root_path=str(root)))
    session.flush()
    session.add(Conversation(id="c", project_id="p"))
    session.flush()
    session.add(Run(id="r", conversation_id="c"))
    session.flush()
    session.add(Agent(id="a", run_id="r", role_name="Lead", tools=[]))
    session.flush()
    session.add(Message(id="m", conversation_id="c", run_id="r", role="assistant"))
    session.flush()
    session.add(ToolCall(id="t", run_id="r", agent_id="a", message_id="m", seq=1, provider_call_id="t",
                         name="write_file", arguments="{}"))
    session.commit()
    yield session, Workspace(root)
    session.close()


def change(session, path, before, after, status="proposed"):
    row = FileChange(run_id="r", agent_id="a", tool_call_id="t", path=path,
                     kind="create" if before is None else "modify",
                     before_content=before, after_content=after,
                     before_sha=sha256_text(before), after_sha=sha256_text(after), status=status)
    session.add(row)
    session.commit()
    return row


def test_apply_creates_the_file(env):
    session, ws = env
    row = change(session, "a/new.txt", None, "x\n")
    assert apply_change(session, ws, row) == "applied"
    assert ws.read_text("a/new.txt") == "x\n"
    assert row.status == "applied" and row.decided_at is not None


def test_apply_refuses_when_the_target_appeared_meanwhile(env):
    session, ws = env
    row = change(session, "new.txt", None, "mine\n")
    ws.write_text("new.txt", "theirs\n")
    assert apply_change(session, ws, row) == "conflict"
    assert ws.read_text("new.txt") == "theirs\n" and row.status == "conflict"


def test_apply_treats_a_now_binary_file_as_a_conflict(env):
    session, ws = env
    ws.write_text("f.txt", "old\n")
    row = change(session, "f.txt", "old\n", "new\n")
    (ws.root / "f.txt").write_bytes(b"\xff\xfe\x00")
    assert apply_change(session, ws, row) == "conflict"
    assert (ws.root / "f.txt").read_bytes() == b"\xff\xfe\x00"


def test_revert_restores_the_previous_bytes(env):
    session, ws = env
    ws.write_text("f.txt", "a\r\nb\n")
    row = change(session, "f.txt", "a\r\nb\n", "a\r\nB\n")
    apply_change(session, ws, row)
    revert_change(session, ws, row)
    assert (ws.root / "f.txt").read_bytes() == b"a\r\nb\n" and row.status == "reverted"


def test_revert_of_a_created_file_removes_it(env):
    session, ws = env
    row = change(session, "new.txt", None, "x")
    apply_change(session, ws, row)
    revert_change(session, ws, row)
    assert not (ws.root / "new.txt").exists()


def test_only_an_applied_change_can_be_reverted(env):
    session, ws = env
    row = change(session, "f.txt", None, "x")
    with pytest.raises(ValueError, match="only an applied change can be reverted"):
        revert_change(session, ws, row)


def test_revert_refuses_when_the_file_is_gone_or_different(env):
    session, ws = env
    ws.write_text("f.txt", "old")
    row = change(session, "f.txt", "old", "new")
    apply_change(session, ws, row)
    ws.delete("f.txt")
    with pytest.raises(ChangeConflict, match="changed since"):
        revert_change(session, ws, row)
    assert row.status == "applied" and not (ws.root / "f.txt").exists()


def test_an_attached_files_change_is_written_from_koloni_s_store_never_where_its_record_says(
        env, tmp_path):
    """K-belge-ciktilari review: a record restored from elsewhere could name any file (a drive's
    too, `D:secret`) - the bytes are found again by the attachment's id in KOLONİ's store."""
    session, ws = env
    runtime = tmp_path / "runtime"
    kept = runtime / "attachments" / "c" / "a1"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"attached")
    (tmp_path / "secret.txt").write_bytes(b"not for the project")

    def attached(path, after_from):
        row = change(session, path, None, "(an attached file)")
        row.after_from = after_from
        session.commit()
        return row

    good = attached("docs/one.png", str(tmp_path / "elsewhere" / "a1"))
    assert apply_change(session, ws, good, runtime) == "applied"
    assert (ws.root / "docs" / "one.png").read_bytes() == b"attached"
    for n, name in enumerate((str(tmp_path / "secret.txt"), "x/D:secret.txt", "a/..")):
        bad = attached(f"docs/bad{n}.png", name)
        with pytest.raises(WorkspaceError, match="no longer kept"):
            apply_change(session, ws, bad, runtime)
        assert bad.status == "failed"
    with pytest.raises(WorkspaceError, match="no longer kept"):
        apply_change(session, ws, attached("docs/two.png", str(kept)))  # (no store named)
