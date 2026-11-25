"""0.1.8 To-do in a chat: goals hold stories, stories hold tasks and bugs (`app.stories`). A
story's state comes from its tasks, a goal's progress from its stories; links stay within a
project; deleting a goal or a story keeps what was under it, deleting the project takes all."""

from datetime import datetime

from app.db.models import BacklogTask, Story
from app.stories import goal_progress, story_state
from tests.test_backlog import ORIGIN, setup


def story(closed: bool = False) -> Story:
    return Story(title="s", closed_at=datetime(2026, 11, 24) if closed else None)


def t(status: str, place: int | None = None) -> BacklogTask:
    return BacklogTask(title="t", status=status, flow={"place": place} if place else None)


def test_a_storys_state_comes_from_its_tasks():
    assert story_state(story(), []) == "todo"
    assert story_state(story(), [t("done"), t("doing")]) == "running"
    assert story_state(story(), [t("todo", place=1)]) == "running"
    assert story_state(story(), [t("done"), t("blocked")]) == "stuck"
    assert story_state(story(), [t("done"), t("done")]) == "done?"
    assert story_state(story(closed=True), [t("todo")]) == "done"
    assert story_state(story(), [t("proposed")]) == "todo"
    assert story_state(story(), [t("done"), t("proposed")]) == "done?"  # (a proposal is not one)
    # (each waiting at "done?" for the user's word: the story's done? too)
    assert story_state(story(), [t("done"), t("review")]) == "done?"
    assert story_state(story(), [t("review"), t("todo")]) == "todo"


def test_goal_progress_counts_closed_stories():
    assert goal_progress(["done", "done?", "running"]) == (1, 3)
    assert goal_progress([]) == (0, 0)


def tree(client, pid):
    return client.get(f"/api/projects/{pid}/stories").json()


def test_a_goal_and_a_story_are_added_listed_and_linked(client, project_dir):
    pid, (task,) = setup(client, project_dir, "find the bug")
    goal = client.post(f"/api/projects/{pid}/goals", json={"title": "Login holds"})
    assert goal.status_code == 201, goal.text
    goal = goal.json()
    made = client.post(
        f"/api/projects/{pid}/stories", json={"title": "Fix login", "goal_id": goal["id"]}
    )
    assert made.status_code == 201, made.text
    story_id = made.json()["id"]
    changed = client.patch(f"/api/backlog/{task}", json={"story_id": story_id, "kind": "bug"})
    assert changed.status_code == 200, changed.text
    assert (changed.json()["story_id"], changed.json()["kind"]) == (story_id, "bug")
    # a task added with its story at once
    added = client.post(
        f"/api/projects/{pid}/backlog", json={"title": "add a test", "story_id": story_id}
    )
    assert added.status_code == 201 and added.json()["kind"] == "task"
    listed = tree(client, pid)
    ((g,),) = [listed["goals"]]
    assert (g["title"], g["stories_done"], g["stories_all"], g["created_by"]) == (
        "Login holds",
        0,
        1,
        "user",
    )
    ((s,),) = [listed["stories"]]
    assert (s["title"], s["goal_id"], s["state"], s["notes"], s["closed_at"]) == (
        "Fix login",
        goal["id"],
        "todo",
        [],
        None,
    )
    # Closed only once each of its tasks is done (review T1: the page offers it only then).
    refused = client.patch(f"/api/stories/{story_id}", json={"closed": True})
    assert refused.status_code == 409, refused.text
    assert "2 of them are not" in refused.json()["detail"]
    for one in client.get(f"/api/projects/{pid}/backlog").json():
        client.patch(f"/api/backlog/{one['id']}", json={"status": "done"})
    # closed by the user: done, and the goal counts it
    closed = client.patch(f"/api/stories/{story_id}", json={"closed": True})
    assert closed.status_code == 200 and closed.json()["state"] == "done"
    assert tree(client, pid)["goals"][0]["stories_done"] == 1
    reopened = client.patch(f"/api/stories/{story_id}", json={"closed": False, "title": "Login"})
    assert (reopened.json()["state"], reopened.json()["title"]) == ("done?", "Login")
    renamed = client.patch(f"/api/goals/{goal['id']}", json={"title": "Sign-in holds"})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Sign-in holds"


def test_only_the_apps_own_page_writes_them(client, project_dir):
    pid, _ = setup(client, project_dir)
    del client.headers["Origin"]
    assert client.post(f"/api/projects/{pid}/goals", json={"title": "g"}).status_code == 403
    assert client.post(f"/api/projects/{pid}/stories", json={"title": "s"}).status_code == 403
    assert client.get(f"/api/projects/{pid}/stories").status_code == 200  # (reading is open)


def test_a_task_is_unlinked_with_null(client, project_dir):
    pid, (task,) = setup(client, project_dir, "a")
    story_id = client.post(f"/api/projects/{pid}/stories", json={"title": "s"}).json()["id"]
    client.patch(f"/api/backlog/{task}", json={"story_id": story_id})
    unlinked = client.patch(f"/api/backlog/{task}", json={"story_id": None})
    assert unlinked.status_code == 200 and unlinked.json()["story_id"] is None
    # a story's goal goes the same way
    goal_id = client.post(f"/api/projects/{pid}/goals", json={"title": "g"}).json()["id"]
    client.patch(f"/api/stories/{story_id}", json={"goal_id": goal_id})
    assert (
        client.patch(f"/api/stories/{story_id}", json={"goal_id": None}).json()["goal_id"] is None
    )


def test_links_across_projects_are_refused(client, project_dir, tmp_path):
    pid, (task,) = setup(client, project_dir, "a")
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other = client.post("/api/projects", json={"root_path": str(other_dir)}).json()["id"]
    theirs = client.post(f"/api/projects/{other}/stories", json={"title": "theirs"}).json()["id"]
    their_goal = client.post(f"/api/projects/{other}/goals", json={"title": "g"}).json()["id"]
    mine = client.post(f"/api/projects/{pid}/stories", json={"title": "mine"}).json()["id"]
    assert client.patch(f"/api/backlog/{task}", json={"story_id": theirs}).status_code == 422
    added = client.post(f"/api/projects/{pid}/backlog", json={"title": "b", "story_id": theirs})
    assert added.status_code == 422
    assert client.patch(f"/api/stories/{mine}", json={"goal_id": their_goal}).status_code == 422
    made = client.post(f"/api/projects/{pid}/stories", json={"title": "x", "goal_id": their_goal})
    assert made.status_code == 422
    assert client.patch(f"/api/backlog/{task}", json={"story_id": "nope"}).status_code == 422
    assert [t["title"] for t in client.get(f"/api/projects/{pid}/backlog").json()] == ["a"]


def test_deleting_a_story_or_goal_keeps_what_was_under_it(client, project_dir):
    pid, (task,) = setup(client, project_dir, "a")
    goal_id = client.post(f"/api/projects/{pid}/goals", json={"title": "g"}).json()["id"]
    story_id = client.post(
        f"/api/projects/{pid}/stories", json={"title": "s", "goal_id": goal_id}
    ).json()["id"]
    client.patch(f"/api/backlog/{task}", json={"story_id": story_id})
    assert client.delete(f"/api/goals/{goal_id}").status_code == 204
    assert tree(client, pid)["stories"][0]["goal_id"] is None
    assert client.delete(f"/api/stories/{story_id}").status_code == 204
    assert tree(client, pid) == {"goals": [], "stories": []}
    (left,) = client.get(f"/api/projects/{pid}/backlog").json()
    assert (left["title"], left["story_id"]) == ("a", None)
    assert client.delete(f"/api/stories/{story_id}").status_code == 404


def test_deleting_a_project_deletes_its_goals_and_stories(client, project_dir):
    pid, (task,) = setup(client, project_dir, "a")
    goal_id = client.post(f"/api/projects/{pid}/goals", json={"title": "g"}).json()["id"]
    story_id = client.post(
        f"/api/projects/{pid}/stories", json={"title": "s", "goal_id": goal_id}
    ).json()["id"]
    client.patch(f"/api/backlog/{task}", json={"story_id": story_id})
    assert client.delete(f"/api/projects/{pid}", headers=ORIGIN).status_code == 204
    from app.db.models import Goal

    with client.app.state.session_factory() as session:
        assert session.query(Goal).count() == 0 and session.query(Story).count() == 0


def test_a_storys_name_is_one_in_its_project_whatever_its_case(client, project_dir, tmp_path):
    """Review T2: an agent names a story by its title, whatever its case - so the project has one
    story of a name, open or closed (another project may have its own)."""
    pid, _ = setup(client, project_dir)
    first = client.post(f"/api/projects/{pid}/stories", json={"title": "Login"}).json()["id"]
    again = client.post(f"/api/projects/{pid}/stories", json={"title": " LOGIN "})
    assert again.status_code == 422 and "“Login”" in again.json()["detail"]
    other = client.post(f"/api/projects/{pid}/stories", json={"title": "Reset"}).json()["id"]
    assert client.patch(f"/api/stories/{other}", json={"title": "login"}).status_code == 422
    # (its own name in another case is no other story's)
    assert client.patch(f"/api/stories/{first}", json={"title": "LOGIN"}).status_code == 200
    tree_in = {"stories": [{"title": "login", "tasks": [{"title": "t"}]}], "tasks": []}
    assert client.post(f"/api/projects/{pid}/backlog/tree", json=tree_in).status_code == 422
    twice = {
        "stories": [
            {"title": "New", "tasks": [{"title": "a"}]},
            {"title": "NEW", "tasks": [{"title": "b"}]},
        ],
        "tasks": [],
    }
    assert client.post(f"/api/projects/{pid}/backlog/tree", json=twice).status_code == 422
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    theirs = client.post("/api/projects", json={"root_path": str(elsewhere)}).json()["id"]
    assert (
        client.post(f"/api/projects/{theirs}/stories", json={"title": "Login"}).status_code == 201
    )
    assert [s["title"] for s in tree(client, pid)["stories"]] == ["LOGIN", "Reset"]
