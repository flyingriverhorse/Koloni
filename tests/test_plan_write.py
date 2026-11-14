"""What `app.tools.plan_write` refuses before anything is written or asked, in its own words."""

import pytest

from app.tools import ToolError, plan_write
from app.workspace import Workspace


@pytest.mark.parametrize("name, args, why", [
    ("edit_file", {"path": "new.txt", "old_string": "a", "new_string": "b"},
     "'new.txt' does not exist; use write_file to create it"),
    ("edit_file", {"path": "a.txt", "old_string": "", "new_string": "b"},
     "old_string must not be empty"),
    ("write_file", {"path": "folder", "content": "x"}, "'folder' is not a file"),
    ("write_file", {"path": "a.txt/b.txt", "content": "x"}, "'a.txt' is a file, not a folder"),
    ("write_file", {"path": "a.txt/b/c.txt", "content": "x"}, "'a.txt' is a file, not a folder"),
    ("write_file", {"path": "a.txt", "content": "one\n"},
     "'a.txt' already has this content; nothing to change"),
    ("delete_file", {"path": "a.txt"}, "unknown tool: delete_file"),
])
def test_a_write_that_cannot_be_made_is_refused_with_why(tmp_path, name, args, why):
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8", newline="")
    (tmp_path / "folder").mkdir()
    with pytest.raises(ToolError) as refused:
        plan_write(Workspace(tmp_path), name, args)
    assert str(refused.value) == why


def test_a_write_and_an_edit_are_planned_without_touching_the_disk(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\n", encoding="utf-8", newline="")
    made = plan_write(Workspace(tmp_path), "write_file", {"path": "folder/new.txt", "content": "x"})
    assert (made.path, made.kind, made.before, made.after) == ("folder/new.txt", "create", None, "x")
    edit = plan_write(Workspace(tmp_path), "edit_file",
                      {"path": "a.txt", "old_string": "two", "new_string": "2"})
    assert (edit.kind, edit.before, edit.after, edit.note) == ("modify", "one\ntwo\n", "one\n2\n", "")
    assert not (tmp_path / "folder").exists()
    assert (tmp_path / "a.txt").read_bytes() == b"one\ntwo\n"
