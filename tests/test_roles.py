import pytest

from app.roles import (
    ALL_TOOLS,
    BROWSER,
    BUILTIN_ROLES,
    DIAGRAM,
    can_change_things,
    effective_tools,
    title_of,
)

READ = ["list_dir", "read_file", "search", "view_image"]  # (28e: view_image)
NOTEBOOK = ["post_note", "read_notes"]
MEMORY = ["remember", "recall"]


def test_effective_tools_is_the_intersection_in_a_fixed_order():
    assert effective_tools(["search", "write_file", "list_dir"], None) == [
        "list_dir", "search", "write_file"]
    assert effective_tools(ALL_TOOLS, READ) == READ
    assert effective_tools(["write_file", "run_command"], READ) == []
    assert effective_tools(["read_file", "teleport"], None) == ["read_file"]


def test_can_change_things():
    assert can_change_things(["read_file", "edit_file"]) is True
    assert can_change_things(["run_command"]) is True
    assert can_change_things(READ + ["spawn_agent", "create_role"]) is False


def test_built_in_roles_match_the_design():
    tools = {name: list(spec.tools) for name, spec in BUILTIN_ROLES.items()}
    assert list(tools) == [
        "Lead", "Planner", "Coder", "Tester", "Reviewer", "Researcher",
        # slice 28a
        "Debugger", "Architect", "Security reviewer", "Docs writer", "Refactorer",
        # slice 43
        "UI designer", "Data analyst", "DevOps", "Spec writer", "Performance engineer",
        "Database engineer", "Dependency keeper", "Translator", "Summarizer",
        # slice 52
        "Product owner", "Assistant product owner",
        # slice 33b: asked by KOLONİ itself, with no tools
        "Observer",
        # K-takim-duzen
        "Data engineer", "ML engineer", "Data scientist", "Model evaluator", "MLOps engineer",
        # K-belge-ciktilari
        "Designer",
        # K-site-roller
        "SEO specialist", "Copywriter", "Accessibility reviewer"]
    assert tools["Lead"] == list(ALL_TOOLS)
    assert tools["Planner"] == READ + [
        "spawn_agent", "create_role", "ask_user", "ask_folder", "message_agent", "discuss",
        "propose_trigger", *NOTEBOOK, *MEMORY]  # (slice 69: it proposes, the user approves)
    # (slice 51: the roles that try a page get the browser after their commands or web)
    # (K-drawio: who writes documents, designs or code draws diagrams, after its file tools)
    assert tools["Coder"] == READ + ["write_file", "edit_file", *DIAGRAM, "run_command", *BROWSER,
                                     "spawn_agent", "ask_user", "message_agent", *NOTEBOOK, *MEMORY]
    assert tools["Tester"] == READ + [
        "run_command", *BROWSER, "ask_user", "message_agent", *NOTEBOOK, *MEMORY]
    assert tools["Reviewer"] == READ + ["ask_user", "message_agent", *NOTEBOOK, *MEMORY]
    # the Researcher also looks things up on the web (slice 18c)
    assert tools["Researcher"] == READ + [
        "web_search", "http_request", *BROWSER, "ask_user", "message_agent", *NOTEBOOK, *MEMORY]
    # slice 28a: who may write, who may run a command, and the tier each asks for
    talk = ["ask_user", "message_agent", *NOTEBOOK, *MEMORY]
    # K-spawn-roller (R121): six more roles open helpers; the ones that read and judge do not
    assert tools["Debugger"] == READ + ["write_file", "edit_file", "run_command", *BROWSER,
                                        "spawn_agent", *talk]
    assert tools["Architect"] == READ + ["spawn_agent", *talk]
    assert tools["Security reviewer"] == READ + talk
    assert tools["Docs writer"] == READ + ["write_file", "edit_file", *DIAGRAM, *talk]
    assert tools["Refactorer"] == READ + ["write_file", "edit_file", "run_command", *talk]
    # slice 43: the nine new roles, each with only what its work needs
    write, run = ["write_file", "edit_file"], ["run_command"]
    assert tools["UI designer"] == READ + write + ["show", *DIAGRAM, *BROWSER, *talk]
    assert tools["Data analyst"] == READ + write + ["show", *run, *talk]
    assert tools["DevOps"] == READ + write + run + ["web_search", "spawn_agent", *talk]
    assert tools["Dependency keeper"] == READ + write + run + ["web_search", *talk]
    # B-190: they write the document asked for (docs/...), as the Docs writer does
    assert tools["Spec writer"] == READ + write + ["spawn_agent", *talk]
    assert tools["Performance engineer"] == tools["Database engineer"] == tools["Refactorer"]
    assert tools["Translator"] == READ + write + talk  # (the Docs writer's, but diagrams)
    assert tools["Summarizer"] == READ + write + ["message_agent", *NOTEBOOK, *MEMORY]
    # slice 52: they keep the backlog, and change nothing in the project
    backlog = ["read_backlog", "add_task", "change_task", "assess_task"]
    assert tools["Product owner"] == READ + [
        "spawn_agent", "ask_user", "message_agent", *backlog, *NOTEBOOK, *MEMORY]
    assert tools["Assistant product owner"] == READ + [
        "ask_user", "message_agent", *backlog, *NOTEBOOK, *MEMORY]
    assert tools["Observer"] == []
    # K-takim-duzen: each takes an existing role's tools as they are - slice 51's browser aside,
    # which only the six roles that try a page hold, and K-drawio's diagrams, the five's
    def without_browser(name):
        return [tool for tool in tools[name] if tool not in (*BROWSER, *DIAGRAM)]

    assert tools["Data engineer"] == tools["ML engineer"] == without_browser("Coder")
    assert tools["Data scientist"] == without_browser("Researcher")
    assert tools["Model evaluator"] == without_browser("Tester")
    assert tools["MLOps engineer"] == tools["DevOps"]
    assert set(tools["Designer"]) == set(tools["UI designer"])  # K-belge-ciktilari
    # K-site-roller: the two who write change files and look at the page; the reviewer only looks
    assert tools["SEO specialist"] == tools["Copywriter"] == READ + write + [*BROWSER, *talk]
    assert tools["Accessibility reviewer"] == READ + [*BROWSER, *talk]
    # slice 81b: no tier (the Lead picks one for each job), and the group each is drawn in
    assert {name: spec.kind for name, spec in BUILTIN_ROLES.items()} == {
        "Lead": "plan", "Planner": "plan", "Coder": "build", "Tester": "check",
        "Reviewer": "check", "Researcher": "plan", "Debugger": "build",
        "Architect": "plan", "Security reviewer": "check", "Docs writer": "write",
        "Refactorer": "build", "UI designer": "build", "Data analyst": "check",
        "DevOps": "ops", "Spec writer": "write", "Performance engineer": "check",
        "Database engineer": "data", "Dependency keeper": "ops", "Translator": "write",
        "Summarizer": "write", "Product owner": "plan",
        "Assistant product owner": "plan", "Observer": "check",
        # K-takim-duzen: the Data, ML and Ops categories; the Model evaluator checks
        "Data engineer": "data", "ML engineer": "ml", "Data scientist": "ml",
        "Model evaluator": "check", "MLOps engineer": "ops", "Designer": "build",
        "SEO specialist": "build", "Copywriter": "build", "Accessibility reviewer": "check"}


def roles(client):
    return {r["name"]: r for r in client.get("/api/roles").json()}


def test_built_in_roles_exist_after_startup(client):
    listed = client.get("/api/roles").json()
    # (Then migration 0103's two experts: the user's own roles.)
    assert [r["name"] for r in listed] == [*BUILTIN_ROLES, "MLflow expert", "Databricks expert"]
    assert len(BUILTIN_ROLES) == 32
    assert all(r["builtin"] and not r["created_by_agent"] for r in listed[:32])
    assert roles(client)["Reviewer"]["tools"] == [
        *READ, "ask_user", "message_agent", *NOTEBOOK, *MEMORY]
    assert roles(client)["Reviewer"]["description"]


def test_create_edit_and_delete_a_role(client):
    created = client.post("/api/roles", json={
        "name": " Documenter ", "description": "Writes docs", "instructions": "Write clearly.",
        "tools": ["write_file", "read_file"]})
    assert created.status_code == 201
    role = created.json()
    assert (role["name"], role["tools"], role["builtin"]) == (
        "Documenter", ["read_file", "write_file"], False)

    patched = client.patch(f"/api/roles/{role['id']}", json={
        "name": "Doc writer", "description": "Docs", "tools": ["read_file"]})
    assert (patched.json()["name"], patched.json()["tools"]) == ("Doc writer", ["read_file"])
    assert patched.json()["instructions"] == "Write clearly."

    assert client.delete(f"/api/roles/{role['id']}").status_code == 204
    assert "Doc writer" not in roles(client)
    assert client.delete(f"/api/roles/{role['id']}").status_code == 404


@pytest.mark.parametrize("body, status, message", [
    ({"name": "  ", "description": "d", "instructions": "", "tools": ["read_file"]}, 422, "name is empty"),
    ({"name": "x" * 61, "description": "d", "instructions": "", "tools": ["read_file"]}, 422, "at most 60"),
    ({"name": "Flyer", "description": "d", "instructions": "", "tools": ["teleport"]}, 422, "unknown tool: teleport"),
    ({"name": "reviewer", "description": "d", "instructions": "", "tools": ["read_file"]}, 409, "already a role named Reviewer"),
    ({"name": "Idle", "description": "d", "instructions": "", "tools": []}, 422, "at least one tool"),
])
def test_invalid_roles_are_refused_with_a_reason(client, body, status, message):
    r = client.post("/api/roles", json=body)
    assert r.status_code == status and message in r.json()["detail"]


def test_built_in_roles_can_be_edited_and_reset_but_not_renamed_or_deleted(client):
    reviewer = roles(client)["Reviewer"]
    edited = client.patch(f"/api/roles/{reviewer['id']}", json={
        "tools": ["read_file", "run_command"], "instructions": "Be strict."})
    assert edited.json()["tools"] == ["read_file", "run_command"]

    renamed = client.patch(f"/api/roles/{reviewer['id']}", json={"name": "Critic"})
    assert renamed.status_code == 422 and "built-in roles keep their name" in renamed.json()["detail"]
    deleted = client.delete(f"/api/roles/{reviewer['id']}")
    assert deleted.status_code == 409 and "cannot be deleted" in deleted.json()["detail"]

    reset = client.post(f"/api/roles/{reviewer['id']}/reset")
    assert reset.json()["tools"] == [
        *READ, "ask_user", "message_agent", *NOTEBOOK, *MEMORY]
    assert reset.json()["instructions"] == BUILTIN_ROLES["Reviewer"].instructions


def test_only_built_in_roles_can_be_reset(client):
    role = client.post("/api/roles", json={
        "name": "Temp", "description": "d", "instructions": "", "tools": ["read_file"]}).json()
    r = client.post(f"/api/roles/{role['id']}/reset")
    assert r.status_code == 409 and "only built-in roles" in r.json()["detail"]


def test_role_changes_need_an_allowed_origin(client):
    r = client.post("/api/roles", headers={"Origin": "http://evil.example"}, json={
        "name": "X", "description": "d", "instructions": "", "tools": ["read_file"]})
    assert r.status_code == 403


def test_no_role_can_be_named_so_that_it_reads_as_the_user():
    import pytest as _pytest

    from app.roles import check_name

    for name in ("You", "the  user", "User", "KOLONI"):
        with _pytest.raises(ValueError, match="cannot be a role's name"):
            check_name(name)
    assert check_name("User tester") == "User tester"


def test_two_old_names_that_read_alike_open_neither_in_the_others_place(tmp_path):
    from sqlalchemy.orm import Session

    from app.db.models import Role
    from app.db.session import make_engine, upgrade_db
    from app.roles import find_role

    db = tmp_path / "r.db"
    upgrade_db(db)
    with Session(make_engine(db)) as session:
        zero_width, bidi = chr(0x200B), chr(0x202E)
        session.add(Role(name=f"Co{zero_width}der", description="", instructions="", tools=["read_file"]))
        session.commit()
        # one old name reads as "Co der": it is found by what agents are shown
        assert find_role(session, "co der").name == f"Co{zero_width}der"
        session.add(Role(name=f"Co{bidi}der", description="", instructions="", tools=["write_file"]))
        session.commit()
        assert find_role(session, "Co der") is None



def test_title_of_names_the_lead_and_a_teams_lead_for_people_only():
    # K-isimler: the role's own name stays "Lead"; a team's lead reads by its team.
    assert title_of("Lead") == "Orchestrator"
    assert title_of("Docs lead", "Docs") == "Docs coordinator"
    assert title_of("Docs lead") == "Docs lead"
    assert title_of("Coder 2") == "Coder 2"
    assert title_of("Lead", "Web app") == "Web app coordinator"
