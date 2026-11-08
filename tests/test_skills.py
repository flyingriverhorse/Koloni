"""Slice 45, past its acceptance set: how a skill's folder is read, what the routes refuse,
what runs unasked and what does not, and what an agent is told of its skills where it
cannot ask for one."""

import contextlib
import os
import sys
from pathlib import Path

import pytest

from app import skills
from app.agent import Ctx
from tests.fakes import Script, ScriptedExecutor
from tests.test_agent_writes import wait_status
from tests.test_chat_flow import text
from tests.test_skill_scenarios import ORIGIN, SKILL_MD, add, give
from tests.test_spawn import begin, call, role_id, step
from tests.test_trigger_scenarios import allow, run_now, trigger


def folder_of(tmp_path, files: dict[str, str | bytes]) -> Path:
    for rel, content in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(content if isinstance(content, bytes) else content.encode())
    return tmp_path


def preview(client, **body):
    return client.post("/api/skills/preview", json=body, headers=ORIGIN)


# --- reading a folder ---------------------------------------------------------------------


def test_frontmatter_lines_and_a_folded_description():
    meta, body = skills.front(
        "---\nname: tidy\ndescription: >\n  Keep it small\n  and plain.\nlicense: 'MIT'\n---\n\nDo it.\n")
    assert meta == {"name": "tidy", "description": "Keep it small and plain.", "license": "MIT"}
    assert body == "Do it."
    assert skills.front("no frontmatter here") == ({}, "no frontmatter here")
    assert skills.front("---\nname: never closed\n")[0] == {}


SECRETS = [
    ".env.local", "prod.env", ".envrc", "_netrc", ".netrc", ".git-credentials", ".pgpass",
    ".my.cnf", ".htpasswd", "auth.json", ".npmrc", ".pypirc", ".yarnrc.yml", "token.txt",
    "main.tfstate", "application_default_credentials.json", "service-account-x.json",
    "putty.ppk", "vault.kdbx", "key.asc", "key.gpg", "a.keytab", "c.p12", "c.pfx",
    "deploy.pem", "credentials.json", "keys/id_rsa", "kubeconfig",
    ".ssh/config", ".aws/config", ".gnupg/x", ".docker/config.json", ".kube/config",
    ".azure/x", "gcloud/x", ".terraform.d/x", ".config/x", "node_modules/a/index.js",
]


def test_a_folder_is_read_without_its_secrets_and_says_what_it_left_out(tmp_path):
    found = skills.read(folder_of(tmp_path, {
        "SKILL.md": SKILL_MD, "tools/run.sh": "echo", "notes.md": "n",
        **{rel: "x" for rel in SECRETS}}))
    assert sorted(found.files) == ["SKILL.md", "notes.md", "tools/run.sh"]
    assert found.scripts == ["tools/run.sh"] and found.license is None
    shown = found.shown()
    for rel in SECRETS:
        top = rel.split("/")[0]
        assert rel in shown["skipped"] or f"{top}/" in shown["skipped"], rel


def test_no_link_of_any_kind_is_followed_or_copied(tmp_path):
    secret = folder_of(tmp_path / "elsewhere", {"secret.txt": "HIDDEN"})
    folder = folder_of(tmp_path / "skill", {"SKILL.md": SKILL_MD})
    os.link(secret / "secret.txt", folder / "hard.txt")  # a hard link needs no rights
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(secret), str(folder / "junction"))
    with contextlib.suppress(OSError):  # (this account may not make one)
        os.symlink(secret / "secret.txt", folder / "soft.txt")
    found = skills.read(folder)
    assert found.files == ["SKILL.md"]
    assert "hard.txt" in found.shown()["skipped"]
    assert all(b"HIDDEN" not in data for data in found.contents.values())


@pytest.mark.parametrize("name", ["$(echo pwned).py", "‘quoted’.py", "a;b.sh", "`x`.js"])
def test_a_script_whose_name_could_run_code_is_refused(tmp_path, name):
    with pytest.raises(skills.SkillError, match="script"):
        skills.read(folder_of(tmp_path, {"SKILL.md": SKILL_MD, f"scripts/{name}": "1"}))


def test_the_caps_hold_before_anything_is_read_whole(tmp_path):
    many = {f"f{i}.txt": "x" for i in range(skills.MAX_FILES)}
    with pytest.raises(skills.SkillError, match="at most 200 files"):
        skills.read(folder_of(tmp_path / "many", {"SKILL.md": SKILL_MD, **many}))
    big = {"big.bin": b"0" * skills.MAX_BYTES}
    with pytest.raises(skills.SkillError, match="at most 5 MiB"):
        skills.read(folder_of(tmp_path / "big", {"SKILL.md": SKILL_MD, **big}))
    long = SKILL_MD + "x" * skills.MAX_SKILL_MD
    with pytest.raises(skills.SkillError, match="SKILL.md is larger"):
        skills.read(folder_of(tmp_path / "long", {"SKILL.md": long}))


@pytest.mark.parametrize(("files", "why"), [
    ({"README.md": "x"}, skills.NOT_A_SKILL),
    ({"SKILL.md": "---\ndescription: no name\n---\n"}, skills.NOT_A_SKILL),
    ({"SKILL.md": "---\nname: ../up\n---\n"}, skills.NOT_A_SKILL),
])
def test_a_folder_that_is_no_skill_is_refused_in_one_plain_message(tmp_path, files, why):
    with pytest.raises(skills.SkillError) as refused:
        skills.read(folder_of(tmp_path, files))
    assert str(refused.value) == why


def test_scripts_are_shown_whole_and_the_licence_falls_back_to_the_frontmatter(tmp_path):
    found = skills.read(folder_of(tmp_path, {
        "SKILL.md": "---\nname: tidy\nlicense: Apache-2.0\n---\nbody\n",
        "check.py": "print('ok')\n", "long.sh": "x" * (skills.MAX_SHOWN + 10)}))
    shown = found.shown()
    assert found.license == "Apache-2.0"
    assert shown["script_texts"]["check.py"] == "print('ok')\n"
    assert shown["script_texts"]["long.sh"].endswith(skills.SHOWN_CUT)


# --- the routes ---------------------------------------------------------------------------


def test_the_routes_are_the_app_s_own_and_unknown_skills_are_refused(make_client, tmp_path, settings):
    client, _model = make_client([])
    folder = folder_of(tmp_path / "tidy", {"SKILL.md": SKILL_MD, "LICENSE": "MIT License\n"})
    assert client.post("/api/skills/preview", json={"folder": str(folder)}).status_code == 403
    shown = preview(client, folder=str(folder))
    assert shown.status_code == 200 and shown.json()["license"] == "MIT License"
    assert "SECRET-BODY" in shown.json()["text"]
    assert not (settings.runtime_root / "skills").exists()  # a preview keeps nothing
    assert client.post("/api/skills", json={"folder": "tidy"}, headers=ORIGIN).status_code == 422
    # what was shown is what is kept: a folder changed since it was read is read again first
    (folder / "notes.md").write_text("new", encoding="utf-8")
    stale = client.post("/api/skills", json={"folder": str(folder), "sha256": shown.json()["sha256"]},
                        headers=ORIGIN)
    assert stale.status_code == 409
    skill = add(client, folder)
    again = client.post("/api/skills", json={"folder": str(folder)}, headers=ORIGIN)
    assert again.status_code == 409
    coder = role_id(client, "Coder")
    assert client.patch(f"/api/skills/{skill['id']}", json={"scripts_run_unasked": False}
                        ).status_code == 403
    assert client.patch(f"/api/roles/{coder}", json={"skills": ["tidy"]}).status_code == 403
    unknown = client.patch(f"/api/roles/{coder}", json={"skills": ["nope"]}, headers=ORIGIN)
    assert unknown.status_code == 422
    assert give(client, "Coder", "tidy")["skills"] == ["tidy"]
    reset = client.post(f"/api/roles/{coder}/reset", headers=ORIGIN).json()
    assert reset["skills"] == []
    # (R125: by its id too, as the Tools page lists it; the role keeps its name)
    by_id = client.patch(f"/api/roles/{coder}", json={"skills": [skill["id"]]}, headers=ORIGIN)
    assert by_id.json()["skills"] == ["tidy"]


def test_a_skill_is_replaced_when_the_user_says_so_and_deleted_from_every_role(
    make_client, tmp_path
):
    client, _model = make_client([])
    folder = folder_of(tmp_path / "tidy", {"SKILL.md": SKILL_MD})
    first = add(client, folder)
    give(client, "Coder", "tidy")
    # the same name but for its case is the same skill
    (folder / "SKILL.md").write_text(SKILL_MD.replace("name: tidy", "name: Tidy"), "utf-8")
    assert client.post("/api/skills", json={"folder": str(folder)}, headers=ORIGIN
                       ).status_code == 409
    replaced = client.post("/api/skills", json={"folder": str(folder), "replace": True},
                           headers=ORIGIN)
    assert replaced.status_code == 201, replaced.text
    second = replaced.json()

    def coder_skills():
        return next(r["skills"] for r in client.get("/api/roles").json() if r["name"] == "Coder")

    # one skill of its name, the new copy only; the role that had it keeps it, by its new name
    assert [s["id"] for s in client.get("/api/skills").json()] == [second["id"]]
    assert second["name"] == "Tidy" and not Path(first["folder"]).exists()
    assert coder_skills() == ["Tidy"]
    assert client.delete(f"/api/skills/{second['id']}").status_code == 403
    assert client.delete(f"/api/skills/{second['id']}", headers=ORIGIN).status_code == 204
    assert client.get("/api/skills").json() == [] and not Path(second["folder"]).exists()
    assert coder_skills() == []
    assert client.delete(f"/api/skills/{second['id']}", headers=ORIGIN).status_code == 404
    # and the name is free again
    add(client, folder)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home folder of the test's own, as KOLONİ's never-opened places read it."""
    home = tmp_path / "userhome"
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    return home


def test_a_folder_in_a_place_koloni_never_opens_is_refused_to_the_user_too(make_client, home):
    client, _model = make_client([])
    folder = folder_of(home / ".claude" / "skills" / "x", {"SKILL.md": SKILL_MD})
    assert preview(client, folder=str(folder)).status_code == 422
    assert client.post("/api/skills", json={"folder": str(folder)}, headers=ORIGIN).status_code == 422


# --- what runs unasked ----------------------------------------------------------------------


@pytest.mark.parametrize("changed", ["check.py", "SKILL.md"])
def test_a_skill_changed_since_it_was_copied_has_its_scripts_asked_about(
    make_client, project_dir, tmp_path, changed
):
    executor = ScriptedExecutor([Script(["ok\n"])])
    client, _model = make_client(
        [step(call("run_skill_script", {"skill": "tidy", "script": "check.py"})), text("ran")],
        executor=executor,
    )
    skill = add(client, folder_of(tmp_path / "tidy", {"SKILL.md": SKILL_MD, "check.py": "1"}))
    Path(skill["folder"], changed).write_text("changed", encoding="utf-8")
    give(client, "Lead", "tidy")
    cid, _run_id = begin(client, project_dir, mode="ask")
    wait_status(client, cid, "waiting_approval")
    assert executor.started == []


def test_python_scripts_run_without_writing_bytecode_into_the_store(tmp_path):
    assert skills.script_line(str(tmp_path), "check.py").startswith("python -B ")


def test_a_trigger_s_turn_runs_a_listed_unchanged_script_and_nothing_else_unasked(
    make_client, wait_run, project_dir, tmp_path
):
    executor = ScriptedExecutor([Script(["ok\n"])])
    where = {}

    async def changed_meanwhile(on_delta):  # the skill changes after its first script ran
        Path(where["folder"], "two.py").write_text("changed", encoding="utf-8")
        return step(call("run_skill_script", {"skill": "tidy", "script": "two.py"}, "changed"))

    client, _model = make_client({"Lead": [
        step(call("run_skill_script", {"skill": "tidy", "script": "check.py"}, "ok")),
        step(call("run_skill_script", {"skill": "tidy", "script": "other.py"}, "unlisted")),
        changed_meanwhile,
        text("done")]}, executor=executor)
    client.headers["Origin"] = "http://127.0.0.1:8790"
    skill = add(client, folder_of(tmp_path / "tidy", {
        "SKILL.md": SKILL_MD, "check.py": "1", "two.py": "2"}))
    where["folder"] = skill["folder"]
    give(client, "Lead", "tidy")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    rule = allow(client, cid, "python hello.py")
    made = trigger(client, pid, cid, permissions={"write": False, "commands": [rule], "agents": 0})
    run_id = run_now(client, made["id"])
    snap = wait_run(client, cid, run_id, timeout=20)
    said = {t["provider_call_id"]: t["status"] for t in snap["tool_calls"]}
    assert said == {"ok": "succeeded", "unlisted": "failed", "changed": "denied"}
    assert len(executor.started) == 1


def test_a_script_does_not_run_in_a_project_that_runs_in_docker(make_client, wait_run, project_dir,
                                                                  tmp_path):
    executor = ScriptedExecutor([Script(["ok\n"])])
    client, _model = make_client(
        [step(call("run_skill_script", {"skill": "tidy", "script": "check.py"})), text("no")],
        executor=executor)
    client.headers["Origin"] = "http://127.0.0.1:8790"
    add(client, folder_of(tmp_path / "tidy", {"SKILL.md": SKILL_MD, "check.py": "1"}))
    give(client, "Lead", "tidy")
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={
        "exec_location": "docker", "docker_image": "alpine"}).status_code == 200
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    client.patch(f"/api/conversations/{cid}", json={"permission_mode": "full_auto"})
    run_id = client.post(f"/api/conversations/{cid}/messages", json={"content": "go"}).json()[
        "run"]["id"]
    snap = wait_run(client, cid, run_id)
    (tried,) = [t for t in snap["tool_calls"] if t["name"] == "run_skill_script"]
    assert tried["status"] == "failed" and "Docker" in tried["result"]
    assert executor.started == []


# --- the Lead's card ------------------------------------------------------------------------


def test_the_lead_s_skill_is_refused_before_a_card_from_a_never_opened_place_or_a_taken_name(
    make_client, wait_run, project_dir, tmp_path, home
):
    hidden = folder_of(home / ".claude" / "skills" / "x", {"SKILL.md": SKILL_MD})
    taken = folder_of(tmp_path / "tidy", {"SKILL.md": SKILL_MD})
    client, _model = make_client([
        step(call("add_skill", {"folder": str(hidden)}, "k1")),
        step(call("add_skill", {"folder": str(taken)}, "k2")),
        step(call("add_skill", {"folder": str(taken), "github": "https://github.com/a/b"}, "k3")),
        text("could not"),
    ])
    add(client, taken)
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    said = {t["provider_call_id"]: t for t in snap["tool_calls"]}
    assert said["k1"]["status"] == "failed" and "never opened" in said["k1"]["result"]
    assert said["k2"]["status"] == "failed" and "Agents page" in said["k2"]["result"]
    assert said["k3"]["status"] == "failed"
    assert snap["pending_skills"] == []


def test_yes_without_leave_for_its_scripts_adds_it_asking_for_them(
    make_client, wait_run, project_dir, tmp_path
):
    folder = folder_of(tmp_path / "tidy", {"SKILL.md": SKILL_MD, "check.py": "1"})
    client, _model = make_client([step(call("add_skill", {"folder": str(folder)}, "k1")),
                                  text("added")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    (card,) = wait_status(client, cid, "waiting_approval")["pending_skills"]
    assert card["script_texts"] == {"check.py": "1"} and card["roles"] == []
    approved = client.post(f"/api/tool-calls/{card['tool_call_id']}/approve",
                           json={"scope": "ask_scripts"}, headers=ORIGIN)
    assert approved.status_code == 200, approved.text
    wait_run(client, cid, run_id)
    (kept,) = client.get("/api/skills").json()
    assert kept["scripts_run_unasked"] is False


def test_nobody_watching_no_skill_is_proposed(make_client, wait_run, project_dir, tmp_path):
    folder = folder_of(tmp_path / "tidy", {"SKILL.md": SKILL_MD})
    client, _model = make_client({"Lead": [step(call("add_skill", {"folder": str(folder)}, "k")),
                                           text("no")]})
    client.headers["Origin"] = "http://127.0.0.1:8790"
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    made = trigger(client, pid, cid, permissions={"write": False, "commands": [], "agents": 0})
    snap = wait_run(client, cid, run_now(client, made["id"]), timeout=20)
    (tried,) = [t for t in snap["tool_calls"] if t["name"] == "add_skill"]
    assert tried["status"] == "denied"
    assert client.get("/api/skills").json() == []


# --- what an agent is told and reads --------------------------------------------------------


def test_use_skill_reads_only_the_skill_s_own_files(make_client, wait_run, project_dir, tmp_path):
    client, _model = make_client([
        step(call("use_skill", {"name": "tidy", "file": "notes.md"}, "u1")),
        step(call("use_skill", {"name": "tidy", "file": "../../proj/hello.py"}, "u2")),
        text("read"),
    ])
    add(client, folder_of(tmp_path / "tidy", {"SKILL.md": SKILL_MD, "notes.md": "NOTES"}))
    give(client, "Lead", "tidy")
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    said = {t["provider_call_id"]: t for t in snap["tool_calls"]}
    assert said["u1"]["result"] == "NOTES"
    assert said["u2"]["status"] == "failed" and "print" not in said["u2"]["result"]


def test_a_cli_working_with_its_own_tools_is_given_its_skills_whole(make_client, tmp_path):
    client, _model = make_client([])
    add(client, folder_of(tmp_path / "tidy", {"SKILL.md": SKILL_MD}))
    give(client, "Coder", "tidy")
    runner = client.app.state.runner
    ctx = Ctx("r", "c", str(tmp_path), "a", "Coder", (), 1)
    assert "SECRET-BODY" in runner._skills_told(ctx, can_ask=False)
    told = runner._skills_told(ctx, can_ask=True)
    assert "tidy: Keep changes small and plain." in told and "SECRET-BODY" not in told
    assert runner._skills_told(Ctx("r", "c", str(tmp_path), "a", "Reviewer", (), 1), True) == ""


@pytest.mark.parametrize("tools", [True, False])
def test_skills_given_whole_in_its_brief_are_on_its_record_so(
    make_client, wait_run, project_dir, tmp_path, tools
):
    # R190: one that cannot call use_skill (here a model that takes no tools; agy natively) is
    # given them whole - Tools › Skills says so, not "given, not read".
    client, _model = make_client([text("done")], tools_supported=tools)
    add(client, folder_of(tmp_path / "tidy", {"SKILL.md": SKILL_MD}))
    give(client, "Lead", "tidy")
    cid, run_id = begin(client, project_dir, mode="full_auto")
    (lead,) = [a for a in wait_run(client, cid, run_id)["agents"] if a["depth"] == 0]
    assert lead["skills"]["given"] == ["tidy"]
    assert lead["skills"]["in_brief"] == ([] if tools else ["tidy"])
    (row,) = client.get("/api/record").json()["skills"]
    assert (row["used"], row["in_brief"]) == (0, 0 if tools else 1)


# --- slice 92: the card says what a skill may use and run ------------------------------------

CARD_MD = (
    "---\nname: deploy\ndescription: Ships it.\nallowed-tools: Read, Bash(git push:*)\n---\n\n"
    "First !`git status` is read.\n\n```bash\nnpm test\n```\n\n```python\nprint(1)\n```\n")


def test_the_card_lists_its_scripts_programs_tools_and_commands(make_client, tmp_path):
    client, _model = make_client([])
    folder = folder_of(tmp_path / "deploy", {
        "SKILL.md": CARD_MD, "tools/run.sh": "echo", "bin/go": "#!/usr/bin/env python\n",
        "setup.bat": "@echo off", "notes.md": "#not a program"})
    shown = preview(client, folder=str(folder)).json()
    assert sorted(shown["files"]) == ["SKILL.md", "bin/go", "notes.md", "setup.bat", "tools/run.sh"]
    assert shown["scripts"] == ["tools/run.sh"]
    assert sorted(shown["programs"]) == ["bin/go", "setup.bat"] and shown["read_whole"] is True
    assert shown["allowed_tools"] == ["Read", "Bash(git push:*)"]
    assert shown["runs_as_it_loads"] == ["First !`git status` is read."]
    assert shown["shell_blocks"] == 1


def test_allowed_tools_as_a_line_a_bracket_or_a_list():
    head = "---\nname: x\n{}\ndescription: y\n---\nbody"
    assert skills.declared(head.format("allowed-tools: [Read, 'Grep']")) == ["Read", "Grep"]
    for listed in ("allowed-tools:\n  - Read\n  - Bash", "allowed-tools:\n- Read\n- Bash"):
        assert skills.declared(head.format(listed)) == ["Read", "Bash"]
    assert skills.declared(head.format("license: MIT")) == []
    assert skills.declared("allowed-tools: Read") == []  # not in a frontmatter


def test_the_card_knows_programs_by_more_endings_and_headers_and_writes_out_hidden_letters(
    tmp_path
):
    turned = "notes\u202egnp.md"  # reads as "notesdm.png"
    shown = skills.read(folder_of(tmp_path, {
        "SKILL.md": CARD_MD, "run.ts": "x", "app.jar": "x", "go.lnk": "x",
        "tool": b"MZ\x90\x00", "elf": b"\x7fELF\x02", turned: "n", "package.json": "{}"})).shown()
    assert sorted(shown["programs"]) == ["app.jar", "elf", "go.lnk", "run.ts", "tool"]
    assert "notes\\u202egnp.md" in shown["files"] and turned not in shown["files"]
