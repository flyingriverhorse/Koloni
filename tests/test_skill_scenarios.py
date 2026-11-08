"""Slice 45's acceptance set, the backend's part: skills for roles. Written before the code.

A skill is a folder in the shape Claude Code reads: a SKILL.md (name and description up top, the
instructions below) and files beside it. KOLONİ keeps its own copy: taken from a folder the user
names (secrets are not copied), or added by the Lead only through a card the user approves. A role
is given skills; its agents are told each one's name and line, and read the whole of one with
`use_skill`. A skill's own scripts run without asking once the user gave that leave, and only
they; the stored copy is never a place an agent can write.

Contract:
- `POST /api/skills` {"folder": str} from the app's own page → 201 `SkillOut` {id, name,
  description, source, license (its LICENSE's first line, or None), folder (the stored copy),
  files, scripts, scripts_run_unasked (default true)}; `GET /api/skills`.
- `RolePatch.skills` / `RoleOut.skills`: the names of the role's skills.
- Tools: `use_skill {name}`; `run_skill_script {skill, script}` (a path inside the skill);
  `add_skill {folder, roles}` → a card in `SnapshotOut.pending_skills`, decided on
  `/api/tool-calls/{id}/approve` like `create_role`.
"""

import json

import pytest

from app.schemas import RoleOut

if "skills" not in RoleOut.model_fields:
    pytest.skip("slice 45 is not built yet", allow_module_level=True)  # written before the code

from tests.fakes import Script, ScriptedExecutor  # noqa: E402
from tests.test_agent_writes import wait_status  # noqa: E402
from tests.test_chat_flow import text  # noqa: E402
from tests.test_spawn import begin, call, role_id, spawn, step  # noqa: E402

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
SKILL_MD = (
    "---\nname: tidy\ndescription: Keep changes small and plain.\n---\n\n"
    "SECRET-BODY Write the least code that works.\n"
)


@pytest.fixture
def skill_dir(tmp_path):
    folder = tmp_path / "tidy"
    (folder / "scripts").mkdir(parents=True)
    (folder / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (folder / "scripts" / "check.py").write_text("print('ok')\n", encoding="utf-8")
    (folder / "LICENSE").write_text("MIT License\n\nCopyright (c) someone\n", encoding="utf-8")
    (folder / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
    return folder


def add(client, folder):
    made = client.post("/api/skills", json={"folder": str(folder)}, headers=ORIGIN)
    assert made.status_code == 201, made.text
    return made.json()


def give(client, role, *skills):
    changed = client.patch(
        f"/api/roles/{role_id(client, role)}", json={"skills": list(skills)}, headers=ORIGIN
    )
    assert changed.status_code == 200, changed.text
    return changed.json()


def test_a_skill_is_copied_from_a_folder_with_its_licence_and_without_secrets(
    make_client, skill_dir
):
    client, _model = make_client([])
    assert client.post("/api/skills", json={"folder": str(skill_dir)}).status_code == 403
    skill = add(client, skill_dir)
    assert (skill["name"], skill["description"]) == ("tidy", "Keep changes small and plain.")
    assert skill["license"].startswith("MIT License")
    assert ".env" not in skill["files"] and "SKILL.md" in skill["files"]
    assert skill["scripts"] == ["scripts/check.py"] and skill["scripts_run_unasked"] is True
    # A copy: what the source folder becomes later is not the skill.
    (skill_dir / "SKILL.md").write_text(
        "---\nname: tidy\ndescription: changed\n---\n", encoding="utf-8"
    )
    (listed,) = client.get("/api/skills").json()
    assert listed["description"] == "Keep changes small and plain."


def test_a_role_s_agents_are_told_its_skills_by_name_and_read_one_whole_on_asking(
    make_client, wait_run, project_dir, skill_dir
):
    client, model = make_client(
        [
            spawn("Coder", "make it tidy"),
            step(call("use_skill", {"name": "tidy"})),
            step(call("use_skill", {"name": "unknown"}, "c2")),
            text("done"),
            text("ok"),
        ]
    )
    add(client, skill_dir)
    assert give(client, "Coder", "tidy")["skills"] == ["tidy"]
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    coder_first = model.calls[1]
    told = json.dumps(coder_first)
    assert "tidy" in told and "Keep changes small and plain." in told
    assert "SECRET-BODY" not in told  # the whole of it only on asking
    assert "use_skill" in json.dumps(model.tool_args[1])
    results = {t["provider_call_id"]: t for t in snap["tool_calls"] if t["name"] == "use_skill"}
    assert "SECRET-BODY" in results["c1"]["result"]
    assert results["c2"]["status"] in ("failed", "denied") and "SECRET-BODY" not in (
        results["c2"]["result"] or ""
    )
    # The Lead has no skills: it is not told of this one.
    assert "Keep changes small and plain." not in json.dumps(model.calls[0])


def test_a_skill_s_own_script_runs_without_asking_once_given_leave_and_nothing_else_does(
    make_client, wait_run, project_dir, skill_dir
):
    executor = ScriptedExecutor([Script(["ok\n"])])
    client, _model = make_client(
        [
            step(call("run_skill_script", {"skill": "tidy", "script": "scripts/check.py"})),
            step(call("run_skill_script", {"skill": "tidy", "script": "../../hello.py"}, "c2")),
            text("checked"),
        ],
        executor=executor,
    )
    skill = add(client, skill_dir)
    give(client, "Lead", "tidy")
    cid, run_id = begin(client, project_dir, mode="ask")  # every other command would be asked
    snap = wait_run(client, cid, run_id)
    assert len(executor.started) == 1
    command, _cwd = executor.started[0]
    assert "check.py" in command and skill["folder"].replace("\\", "/") in command.replace(
        "\\", "/"
    )
    refused = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "c2")
    assert refused["status"] in ("failed", "denied")


def test_without_that_leave_a_skill_s_script_is_asked_for(make_client, project_dir, skill_dir):
    executor = ScriptedExecutor([Script(["ok\n"])])
    client, _model = make_client(
        [
            step(call("run_skill_script", {"skill": "tidy", "script": "scripts/check.py"})),
            text("checked"),
        ],
        executor=executor,
    )
    skill = add(client, skill_dir)
    changed = client.patch(
        f"/api/skills/{skill['id']}", json={"scripts_run_unasked": False}, headers=ORIGIN
    )
    assert changed.status_code == 200, changed.text
    give(client, "Lead", "tidy")
    cid, _run_id = begin(client, project_dir, mode="ask")
    wait_status(client, cid, "waiting_approval")
    assert executor.started == []


def test_the_lead_adds_a_skill_only_through_a_card_the_user_approves(
    make_client, wait_run, project_dir, skill_dir
):
    client, _model = make_client(
        [
            step(call("add_skill", {"folder": str(skill_dir), "roles": ["Coder"]}, "k1")),
            text("added"),
        ]
    )
    cid, run_id = begin(client, project_dir, mode="full_auto")  # even at full auto: a card
    snap = wait_status(client, cid, "waiting_approval")
    (card,) = snap["pending_skills"]
    assert client.get("/api/skills").json() == []
    approved = client.post(f"/api/tool-calls/{card['tool_call_id']}/approve", headers=ORIGIN)
    assert approved.status_code == 200, approved.text
    wait_run(client, cid, run_id)
    assert [s["name"] for s in client.get("/api/skills").json()] == ["tidy"]
    coder = next(r for r in client.get("/api/roles").json() if r["name"] == "Coder")
    assert coder["skills"] == ["tidy"]


def test_the_stored_copy_is_no_place_an_agent_writes(make_client, wait_run, project_dir, skill_dir):
    where = {}

    async def write_into_the_store(on_delta):  # (where the copy is, is known once it is made)
        return step(call("write_file", {"path": where["target"], "content": "changed"}))

    client, _model = make_client([write_into_the_store, text("tried")])
    skill = add(client, skill_dir)
    where["target"] = f"{skill['folder']}/SKILL.md"
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    (tried,) = [t for t in snap["tool_calls"] if t["name"] == "write_file"]
    assert tried["status"] in ("failed", "denied")
    assert snap["file_changes"] == []
