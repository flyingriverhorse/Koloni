"""What `PATCH /api/conversations/{id}` and `PATCH /api/projects/{id}` refuse, and in which
order: a request that breaks two rules is refused for the first one. Written before the two
handlers were split by groups of fields (C901), to hold the split to what they did."""

import pytest

import app.git
import app.web

OWN = {"Origin": "http://127.0.0.1:8790"}  # as the app's own page says where it is from
NO_ORIGIN = (403, "origin not allowed")
PROJECT_WIDE = (422, "set in Settings › This project: every chat of the project follows it")
NATIVE = (
    409,
    "An agent is working with its own tools, which KOLONİ cannot stop to ask about. "
    "Stop the turn before lowering the permission level.",
)
NO_PARTS = (422, "a chat with no folder has no parts")
DOCKER = (422, "choose a Docker image first")
NO_PR = (422, "a pull request cannot be opened: gh is not here")
LINKS = (422, "a project to look in is another project of this KOLONİ")
DAY_NOTE = (
    422,
    "the day's summary is sent as a desktop notification: keep it on, or empty the summary's time",
)


def address(name: str) -> tuple[int, str]:
    return 422, f"{name} must be an http or https address, without a user name or password"


def answer(client, url: str, body: dict, own: bool = True) -> tuple[int, object]:
    # (`request`: the test client's own `patch` sends a chat's project-wide fields elsewhere.)
    r = client.request("PATCH", url, json=body, headers=OWN if own else {})
    return r.status_code, r.json().get("detail") if r.status_code != 200 else r.json()


@pytest.fixture
def plain(client) -> str:
    return f"/api/conversations/{client.post('/api/conversations', json={}).json()['id']}"


@pytest.fixture
def pid(client, project_dir) -> str:
    return client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]


@pytest.fixture
def chat(client, pid) -> str:
    return f"/api/conversations/{client.post(f'/api/projects/{pid}/conversations').json()['id']}"


@pytest.fixture
def missing(tmp_path) -> tuple[str, tuple[int, str]]:
    """A folder that is not there, and how it is refused."""
    folder = str(tmp_path / "not-there")
    return folder, (422, f"{folder} is not an existing folder")


def test_a_chat_takes_each_group_of_fields(client, plain, tmp_path):
    (tmp_path / "other").mkdir()
    sent = {
        "title": "  a   new \n name ",
        "permission_mode": "auto_edit",
        "spawn_approval": "always",
        "spawn_max_depth": 2,
        "spawn_max_agents": 3,
        "spawn_max_parallel": 4,
        "lead_auto": True,
        "plan_first": True,
        "page_scripts": True,
        "lead_work": "itself",
        "when_away": "lead",
        "away_minutes": 7,
        "teams_mode": "none",
        "lead_effort": "low",
        "discussion_budget": 9000,
        "room_posts": 5,
        "room_tokens": 6000,
        "room_minutes": 7,
        "room_min_tokens": 8,
        "also_in": [str(tmp_path / "other")],
        "part": ".",
        "archived": True,
    }
    status, out = answer(client, plain, sent)
    assert status == 200, out
    want = {
        **sent,
        "title": "a new name",
        "also_in": [str((tmp_path / "other").resolve())],
        "part": None,
    }
    del want["archived"]
    assert {name: out[name] for name in want} == want and out["archived_at"]
    # (The switch of slice 48, where `lead_work` is not sent; and back out of the archive.)
    status, out = answer(client, plain, {"lead_hands_code": True, "archived": False})
    assert (status, out["lead_work"], out["archived_at"]) == (200, "delegates", None)


@pytest.mark.parametrize(
    "body",
    [
        {"permission_mode": "full_auto"},
        {"spawn_approval": "never"},
        {"spawn_max_depth": 2},
        {"spawn_max_agents": 2},
        {"spawn_max_parallel": 2},
        {"page_scripts": True},
        {"lead_work": "itself"},
        {"lead_work": "decides"},
        {"lead_hands_code": False},
        {"when_away": "lead"},
        {"away_minutes": 5},
        {"teams_mode": "none"},
        {"teams": []},
        {"lead_effort": None},
        {"discussion_budget": None},
        {"room_posts": None},
        {"room_tokens": 5},
        {"room_minutes": None},
        {"room_min_tokens": None},
        {"part": None},
        {"archived": True},
        {"archived": False},
        {"after_change": "off"},
        {"after_change": None},
    ],
)
def test_a_chat_takes_these_only_from_the_apps_own_page(client, plain, body):
    # (With a choice of model nobody has: asked where it is from before that is looked at.)
    assert answer(client, plain, {**body, "provider_id": "nope"}, own=False) == NO_ORIGIN
    assert answer(client, plain, body)[0] == 200


def test_a_chat_takes_these_from_anybody(client, plain, tmp_path):
    (tmp_path / "other").mkdir()
    assert answer(client, plain, {"also_in": [str(tmp_path / "other")]}, own=False) == NO_ORIGIN
    assert answer(client, plain, {"read_in": [str(tmp_path / "other")]}, own=False) == NO_ORIGIN
    assert answer(client, plain, {"read_in": [str(tmp_path / "other")]})[0] == 200
    for body in (
        {"title": "named"},
        {"permission_mode": "ask"},
        {"lead_auto": True},
        {"plan_first": True},
        {"page_scripts": False},
        {"lead_work": "delegates"},
        {"lead_hands_code": True},
        {"also_in": []},
        {"provider_id": None},
    ):
        assert answer(client, plain, body, own=False)[0] == 200, body
    # (Planning switched off, and a folder to read in taken off, are leave given.)
    assert answer(client, plain, {"plan_first": False}, own=False) == NO_ORIGIN
    assert answer(client, plain, {"read_in": []}, own=False) == NO_ORIGIN


def test_a_chat_is_refused_for_the_first_rule_it_breaks(
    client, app, plain, chat, missing, monkeypatch
):
    folder, not_there = missing
    monkeypatch.setattr(app.state.runner, "native_active", lambda cid: True)
    empty, moved, lowered = {"title": " \n "}, {"project_id": "nope"}, {"permission_mode": "ask"}
    teams = {"teams_mode": "manual", "teams": [{"team_id": "nope"}]}
    folders, part, choice = {"also_in": [folder]}, {"part": "core/"}, {"provider_id": "nope"}
    # Each alone, as it is refused; then each with the next one: the first one's refusal.
    assert answer(client, chat, {**empty, "spawn_max_depth": 2}) == PROJECT_WIDE
    assert answer(client, chat, {"lead_hands_code": True}, own=False) == PROJECT_WIDE
    assert answer(client, plain, empty) == (422, "title is empty")
    assert answer(client, plain, {**empty, "permission_mode": "full_auto"}, own=False) == (
        422,
        "title is empty",
    )
    assert answer(client, plain, {**empty, **moved}) == (422, "title is empty")
    assert answer(client, plain, moved) == (404, "project not found")
    assert answer(client, plain, moved, own=False) == NO_ORIGIN
    assert answer(client, plain, {"project_id": None}, own=False)[0] == 200  # (where it is)
    assert answer(client, plain, {**moved, **lowered}) == (404, "project not found")
    assert answer(client, plain, lowered) == NATIVE
    assert answer(client, plain, {**lowered, **teams}) == NATIVE
    assert answer(client, plain, teams) == (422, "unknown team")
    assert answer(client, plain, {**teams, **folders}) == (422, "unknown team")
    assert answer(client, plain, folders) == not_there
    assert answer(client, plain, {"read_in": [folder]}) == not_there
    assert answer(client, plain, {**folders, **part}) == not_there
    assert answer(client, plain, part) == NO_PARTS
    assert answer(client, plain, {**part, **choice}) == NO_PARTS
    assert answer(client, plain, choice) == (422, "unknown provider")
    status, why = answer(client, chat, {"part": "no-such-part/"})
    assert status == 422 and "is not one of the project's parts" in why, why


def test_a_project_takes_each_group_of_fields(client, pid, tmp_path, monkeypatch):
    monkeypatch.setattr(app.web, "has_desktop", lambda: True)
    monkeypatch.setattr(app.git, "pr_ready", lambda root: ("owner/repo", None))
    (tmp_path / "other").mkdir()
    sent = {
        "docker_image": " python:3.12 ",
        "docker_network": True,
        "exec_location": "docker",
        "search_url": " http://127.0.0.1:9/search ",
        "search_order": "cli",
        "search_agy": True,
        "notify_desktop": True,
        "turn_token_limit": 5000,
        "max_agents": 3,
        "continue_steps": 4,
        "monthly_budget": 12.5,
        "measure_command": " score ",
        "git_commit": True,
        "finish_way": "pull_request",
        "auto_notes": True,
        "memory_links": [],
        "suggest_tasks": True,
        "suggest_tier": "fast",
        "also_in": [str(tmp_path / "other")],
        "read_in": [],
        "teams_mode": "none",
        "day_note_at": "09:30",
        "hide_secrets": False,
        "pass_env": " A_KEY ",
        "canary": False,
        "lead_work": "itself",
        "when_away": "lead",
        "away_minutes": 7,
        "spawn_approval": "always",
        "spawn_max_depth": 2,
        "spawn_max_agents": 3,
        "spawn_max_parallel": 4,
        "discussion_budget": 9000,
        "room_posts": 5,
        "room_tokens": 6000,
        "room_minutes": 7,
        "room_min_tokens": 8,
        "after_change": "tests",
        "judge_words": True,
        "judge_risky": "ask",
        "disposable_deletes": True,
    }
    status, out = answer(client, f"/api/projects/{pid}", sent)
    assert status == 200, out
    want = {
        **sent,
        "docker_image": "python:3.12",
        "search_url": "http://127.0.0.1:9/search",
        "measure_command": "score",
        "pass_env": "A_KEY",
        "also_in": [str((tmp_path / "other").resolve())],
    }
    assert {name: out[name] for name in want} == want
    # (With the desktop off the day's summary has nowhere to go: not kept.)
    assert answer(client, f"/api/projects/{pid}", {"notify_desktop": False}) == DAY_NOTE
    # (What an empty text and a null take away again.)
    status, out = answer(
        client,
        f"/api/projects/{pid}",
        {
            "measure_command": " ",
            "pass_env": "",
            "search_url": "",
            "turn_token_limit": None,
            "max_agents": None,
            "monthly_budget": None,
            "room_posts": None,
        },
    )
    assert status == 200, out
    assert [
        out[name]
        for name in (
            "measure_command",
            "pass_env",
            "search_url",
            "turn_token_limit",
            "max_agents",
            "monthly_budget",
            "room_posts",
        )
    ] == [None] * 7


@pytest.mark.parametrize(
    "body",
    [
        {"search_order": "cli"},
        {"search_url": ""},
        {"search_agy": False},
        {"notify_desktop": False},
        {"measure_command": ""},
        {"git_commit": False},
        {"finish_way": "merge"},
        {"auto_notes": False},
        {"suggest_tasks": False},
        {"suggest_tier": "fast"},
        {"hide_secrets": True},
        {"pass_env": ""},
        {"canary": True},
        {"lead_work": "delegates"},
        {"continue_steps": 5},
        {"memory_links": []},
        {"when_away": "waits"},
        {"away_minutes": 0},
        {"spawn_approval": "auto"},
        {"spawn_max_depth": 1},
        {"spawn_max_agents": 1},
        {"spawn_max_parallel": 1},
        {"turn_token_limit": None},
        {"discussion_budget": None},
        {"room_posts": None},
        {"room_tokens": None},
        {"room_minutes": None},
        {"room_min_tokens": None},
        {"max_agents": None},
        {"day_note_at": None},
        {"monthly_budget": None},
        {"after_change": "nothing"},
        {"teams_mode": "none"},
        {"teams": []},
        {"also_in": []},
        {"read_in": []},
        {"judge_words": False},
        {"judge_risky": "ask"},
        {"disposable_deletes": False},
        {"forget_tests_found": True},
        {"fix_rounds": 3},
        {"check_kinds": {"slides": False}},
    ],
)
def test_a_project_takes_these_only_from_the_apps_own_page(client, pid, body):
    assert answer(client, f"/api/projects/{pid}", body, own=False) == NO_ORIGIN
    assert answer(client, f"/api/projects/{pid}", body)[0] == 200


def test_a_project_is_refused_for_the_first_rule_it_breaks(client, pid, missing, monkeypatch):
    folder, not_there = missing
    monkeypatch.setattr(app.web, "has_desktop", lambda: False)
    monkeypatch.setattr(app.git, "pr_ready", lambda root: (None, "gh is not here"))
    url = f"/api/projects/{pid}"
    docker, teams = (
        {"exec_location": "docker"},
        {"teams_mode": "manual", "teams": [{"team_id": "nope"}]},
    )
    pull, desktop, links = (
        {"finish_way": "pull_request"},
        {"notify_desktop": True},
        {"memory_links": [pid]},
    )
    search = {"search_url": "ftp://x/"}
    day = {"day_note_at": "09:00"}
    # Where its commands run is anybody's to say - and looked at before where the rest is from.
    assert answer(client, url, {"docker_image": "", "docker_network": True}, own=False)[0] == 200
    assert answer(client, url, {**docker, "search_url": "http://127.0.0.1:9/"}, own=False) == DOCKER
    assert answer(client, url, {**docker, **teams}) == DOCKER
    # Where each of the rest is from is asked before it is looked at: what would be refused
    # from the app's own page is, from anywhere else, refused for that.
    for later in (pull, desktop, links, search, day):
        assert answer(client, url, later, own=False) == NO_ORIGIN, later
        assert answer(client, url, {"measure_command": "x", **later}, own=False) == NO_ORIGIN, later
    assert answer(client, url, teams) == (422, "unknown team")
    assert answer(client, url, {**teams, "also_in": [folder]}) == (422, "unknown team")
    assert answer(client, url, {"also_in": [folder], "read_in": ["not absolute"]}) == not_there
    assert answer(client, url, {"read_in": [folder], **pull}) == not_there
    assert answer(client, url, pull) == NO_PR
    assert answer(client, url, {**pull, **desktop}) == NO_PR
    assert answer(client, url, desktop) == (422, app.web.NO_DESKTOP)
    assert answer(client, url, {**desktop, **links}) == (422, app.web.NO_DESKTOP)
    assert answer(client, url, links) == LINKS
    assert answer(client, url, {"memory_links": ["nope"], **search}) == LINKS
    assert answer(client, url, {**search, **day}) == address("search_url")
    assert answer(client, url, day) == DAY_NOTE
    # (As the project is after the change: with somewhere to send it, the time is kept.)
    monkeypatch.setattr(app.web, "has_desktop", lambda: True)
    status, out = answer(client, url, {**day, **desktop})
    assert (status, out["day_note_at"]) == (200, "09:00")
    assert answer(client, url, {"notify_desktop": False}) == DAY_NOTE
    assert answer(client, "/api/projects/nope", docker) == (404, "project not found")
