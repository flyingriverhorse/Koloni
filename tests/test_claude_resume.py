"""27 / 93-C3: Claude Code goes on in the session its last turn left, sent only what is new -
where it was started under all the same, signed in for KOLONİ alone; else, and once where that
fails at once, anew with the whole conversation."""

import asyncio
import json
from datetime import timedelta
from pathlib import Path

import pytest

from app.commands import names_secret
from app.config import load_settings
from app.db.models import Agent, Message, Question, ToolCall, now
from app.main import create_app
from app.model_agy import AgyClient
from app.model_client import OwnStop
from app.model_native import (
    RESUMED,
    ClaudeNativeClient,
    CodexNativeClient,
    CopilotNativeClient,
    QoderNativeClient,
    forget_session,
    since_its_last_word,
)
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_claude_native import FAKE, WRITE, hello, start

OWN = {"Origin": "http://127.0.0.1:8790"}  # (what is gone for good is asked from the app)
SYSTEM = {"role": "system", "content": "You are the Lead."}
FIRST = [SYSTEM, {"role": "user", "content": "fix the greeting"}]
SECOND = [*FIRST, {"role": "assistant", "content": "Done."},
          {"role": "user", "content": "now the tests"}]


@pytest.fixture
def fake(tmp_path):
    record, plan = tmp_path / "record.json", tmp_path / "plan.json"
    home = tmp_path / "runtime" / "cli-homes" / "p1"  # (as `limits.cli_home` lays it out)

    def make(script=({"say": "Done."},), sessions=("sess-0001",), home_given=True, session_id="sess-0001",
             **more):
        plan.write_text(json.dumps({"record": str(record), "script": list(script),
                                    "session_id": session_id, "sessions": list(sessions),
                                    **more}), encoding="utf-8")
        return ClaudeNativeClient(launcher=FAKE, timeout=30, env={"FAKE_CLI_PLAN": str(plan)},
                                  home=home if home_given else None)

    make.home = home
    make.starts = lambda: [json.loads(line) for line in
                           (tmp_path / "record.json.starts").read_text("utf-8").splitlines()] \
        if (tmp_path / "record.json.starts").exists() else []
    make.record = lambda: json.loads(record.read_text(encoding="utf-8"))
    make.stdin = lambda: make.record()["stdin"]
    return make


def run(cli, root, messages, session=None, level="full_auto", withheld=(), keep=True, **more):
    async def call_tool(name, arguments):
        return True, "{}"

    async def nothing(*_args):
        return None

    return asyncio.run(cli.run_native(
        "claude-sonnet", messages, [], str(root), call_tool, nothing, nothing,
        withheld=withheld, session=session, level=level, keep=keep, **more))


def transcript(home, number="sess-0001"):
    """Where Claude Code is taken to keep a session (`forget_session`), made by hand."""
    kept = home / "projects" / "C--work" / f"{number}.jsonl"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text("{}", encoding="utf-8")
    return kept


def test_the_first_turn_starts_anew_and_keeps_its_session_in_kolonis_folder(fake, tmp_path):
    result = run(fake(), tmp_path, FIRST)
    (argv,) = fake.starts()
    assert "--resume" not in argv and "--no-session-persistence" not in argv
    assert result.session["id"] == "sess-0001" and result.session["under"]
    assert result.session["home"] == str(fake.home)
    assert "fix the greeting" in fake.stdin()


def test_a_run_whose_session_is_not_kept_keeps_none(fake, tmp_path):
    # (A discussion's, and `cli_surface`'s lines: nothing written for them.)
    result = run(fake(), tmp_path, FIRST, keep=False)
    assert "--no-session-persistence" in fake.starts()[-1] and result.session is None
    kept = run(fake(), tmp_path, FIRST).session
    run(fake(), tmp_path, SECOND, session=kept, keep=False)
    assert "--resume" not in fake.starts()[-1]


def test_the_next_turn_resumes_it_with_only_the_new_message(fake, tmp_path):
    cli = fake()
    kept = run(cli, tmp_path, FIRST).session
    result = run(cli, tmp_path, SECOND, session=kept)
    argv = fake.starts()[-1]
    assert argv[argv.index("--resume") + 1] == "sess-0001"
    told = fake.stdin()
    assert "now the tests" in told and RESUMED in told and "You are the Lead." in told
    assert "fix the greeting" not in told and "Done." not in told
    # Its restrictions are this run's own, as for a new session.
    assert {"--permission-prompt-tool", "--disallowedTools", "--strict-mcp-config"} <= set(argv)
    assert result.session == kept


@pytest.mark.parametrize("planted", ["--settings=x", "--dangerously-skip-permissions"])
def test_a_session_id_that_is_no_uuid_is_never_put_on_its_line(fake, tmp_path, planted):
    kept = run(fake(), tmp_path, FIRST).session
    run(fake(sessions=[planted]), tmp_path, SECOND, session={**kept, "id": planted})
    assert "--resume" not in fake.starts()[-1] and planted not in fake.starts()[-1]
    assert run(fake(session_id="a b"), tmp_path, FIRST).session is None  # (nor kept)


def test_a_session_it_does_not_have_falls_back_once_to_the_whole_conversation(fake, tmp_path):
    kept = run(fake(), tmp_path, FIRST).session
    run(fake(sessions=()), tmp_path, SECOND, session=kept)
    resumed, anew = fake.starts()[-2:]
    assert "--resume" in resumed and "--resume" not in anew
    assert len(fake.starts()) == 3  # (never more than once)
    assert "fix the greeting" in fake.stdin() and "now the tests" in fake.stdin()


def test_the_fallback_has_a_tool_server_of_its_own(fake, tmp_path):
    # The resumed one took its MCP server's key before it failed: the next is served anew.
    kept = run(fake(), tmp_path, FIRST).session
    result = run(fake(sessions=(), resume_late=True), tmp_path, SECOND, session=kept)
    assert ["--resume" in argv for argv in fake.starts()] == [False, True, False]
    assert fake.record()["tools"] is not None and result.session["id"] == "sess-0001"


def test_what_koloni_said_before_it_started_does_not_keep_it_from_starting_anew(fake, tmp_path):
    # (Its own sub-agents not given - this fake's version is older than 89g's - is said first.)
    kept = run(fake(), tmp_path, FIRST).session
    run(fake(sessions=()), tmp_path, SECOND, session=kept,
        inside={"koloni-checker": {"description": "d", "prompt": "p"}})
    assert ["--resume" in argv for argv in fake.starts()] == [False, True, False]


def test_a_resumed_run_that_did_something_before_it_failed_is_not_run_again(fake, tmp_path):
    kept = run(fake(), tmp_path, FIRST).session
    with pytest.raises(Exception, match="boom"):
        run(fake(script=[{"say": "half"}, {"fail": "boom"}]), tmp_path, SECOND, session=kept)
    assert ["--resume" in argv for argv in fake.starts()] == [False, True]


@pytest.mark.parametrize("change", ["level", "folder", "withheld", "account"])
def test_another_level_folder_leave_or_account_starts_anew(fake, tmp_path, change):
    kept = run(fake(), tmp_path, FIRST).session
    other = tmp_path / "other"
    other.mkdir()
    cli = fake()
    if change == "account":  # (another sign-in folder of KOLONİ's)
        cli = ClaudeNativeClient(launcher=FAKE, timeout=30, env=dict(cli._env),
                                 home=tmp_path / "runtime" / "cli-homes" / "p2")
    result = run(cli, other if change == "folder" else tmp_path, SECOND, session=kept,
                 level="ask" if change == "level" else "full_auto",
                 withheld=("write",) if change == "withheld" else ())
    assert "--resume" not in fake.starts()[-1] and len(fake.starts()) == 2
    assert "fix the greeting" in fake.stdin()
    assert result.session["under"] != kept["under"]


def test_with_the_users_own_claude_folder_nothing_is_kept_or_resumed(fake, tmp_path):
    cli = fake(home_given=False)
    result = run(cli, tmp_path, FIRST)
    assert result.session is None
    kept = {"id": "sess-0001", "under": cli._under("claude-sonnet", str(tmp_path), (), (), (),
                                              "full_auto")}
    run(cli, tmp_path, SECOND, session=kept)
    assert all("--no-session-persistence" in argv and "--resume" not in argv
               for argv in fake.starts())


def test_only_what_came_after_its_last_answer_is_new():
    assert since_its_last_word(FIRST) == []  # (none of its own yet: anew)
    asked = [*FIRST, {"role": "assistant", "content": "", "tool_calls": [{"id": "c"}]},
             {"role": "tool", "tool_call_id": "c", "content": "ok"},
             {"role": "user", "content": "a note"}, {"role": "user", "content": "next"}]
    assert [m["content"] for m in since_its_last_word(asked)] == ["a note", "next"]
    assert since_its_last_word([*FIRST, {"role": "assistant", "content": "Done."}]) == []


def test_a_session_forgotten_leaves_no_transcript_and_nothing_outside_kolonis_folders(tmp_path):
    runtime = tmp_path / "runtime"
    home = runtime / "cli-homes" / "p1"
    gone, other = transcript(home), transcript(home, "sess-0002")
    (home / "file-history" / "sess-0001").mkdir(parents=True)
    forget_session({"id": "sess-0001", "home": str(home)}, runtime)
    assert not gone.exists() and not (home / "file-history" / "sess-0001").exists()
    own = tmp_path / "own" / ".claude"
    # The user's own folder, one planted to climb back into it, another place's `cli-homes`.
    kept = [transcript(own), transcript(tmp_path / "x" / "cli-homes" / "p1")]
    for planted in (own, own / "cli-homes" / "..", tmp_path / "x" / "cli-homes" / "p1"):
        forget_session({"id": "sess-0001", "home": str(planted)}, runtime)
    forget_session({"id": "*", "home": str(home)}, runtime)
    assert all(one.exists() for one in kept) and other.exists()


@pytest.mark.parametrize("command", [
    'cat "$CLAUDE_CONFIG_DIR"/projects/*/*.jsonl', "ls ${CODEX_HOME}", "type %COPILOT_HOME%\\x",
    "Get-ChildItem $env:CLAUDE_CONFIG_DIR -Recurse", "gc env:claude_config_dir",
    'cat "$(printenv CLAUDE_CONFIG_DIR)"/projects/x.jsonl',
    "python -c \"import os; print(open(os.environ['CLAUDE_CONFIG_DIR'] + '/x').read())\"",
    '[Environment]::GetEnvironmentVariable("CLAUDE_CONFIG_DIR")',
    "cmd /v /c type !CLAUDE_CONFIG_DIR!\\x", "rg CODEX_HOME app/",  # (a search too: taken)
])
def test_a_command_naming_a_sign_in_folder_by_its_variable_is_asked_as_a_secret(command):
    assert names_secret(command)


def test_a_variable_that_only_begins_so_is_not_one():
    assert not names_secret("echo $CLAUDE_CONFIG_DIRECTORY_NOTES")
    assert not names_secret("echo $MY_CODEX_HOME") and not names_secret("ls my-codex_home")


# --- in the app: a later turn's lead -------------------------------------------------------


@pytest.fixture
def chat(settings_env, project_dir, wait_run, fake):
    app = create_app(load_settings(settings_env), model=ScriptedModel([], model_id="big"),
                     clients={"Claude": fake()})
    with TestClient(app, base_url="http://127.0.0.1:8790") as client:
        provider = client.post("/api/providers", json={
            "name": "Claude", "kind": "claude_cli", "mode": "native"}).json()
        cid, run_id = start(client, project_dir, provider, "full_auto")
        wait_run(client, cid, run_id, timeout=30)

        def turn(words):
            run_id = client.post(f"/api/conversations/{cid}/messages",
                                 json={"content": words}).json()["run"]["id"]
            snap = wait_run(client, cid, run_id, timeout=30)
            assert snap["runs"][-1]["status"] == "completed", snap["runs"][-1]["error"]

        turn.client, turn.cid, turn.db = client, cid, app.state.session_factory
        yield turn


def leads(chat):
    with chat.db() as session:
        return session.query(Agent).filter(Agent.parent_agent_id.is_(None)).order_by(
            Agent.created_at).all()


def test_the_next_turns_lead_goes_on_in_the_session_unless_the_level_changed(
    chat, fake, project_dir
):
    # Resumed, its own write is asked about and done as in a new session.
    fake(script=[{**WRITE, "input": {**WRITE["input"], "file_path": (
        project_dir / "hello.py").as_posix()}}, {"say": "Done."}])
    chat("now the tests")
    argv = fake.starts()[-1]
    assert argv[argv.index("--resume") + 1] == "sess-0001"
    assert "now the tests" in fake.stdin() and "fix the greeting" not in fake.stdin()
    assert hello(project_dir) == "print('hello')\n"
    assert [hook["hookSpecificOutput"]["permissionDecision"]
            for hook in fake.record()["hooks"]] == ["ask"]
    assert fake.record()["asked"][0]["behavior"] == "allow"
    # Taken over by the later lead: one session goes on in one run at a time.
    assert [lead.cli_session is not None for lead in leads(chat)] == [False, True]
    # A turn with a write of its own goes on too.
    fake(script=[{"say": "Tested."}])
    chat("and the tests")
    assert "--resume" in fake.starts()[-1]
    chat.client.patch(f"/api/conversations/{chat.cid}", json={"permission_mode": "ask"})
    kept = transcript(fake.home)
    fake(session_id="sess-0002")  # (only words: at Ask a write would wait for the user)
    chat("and the docs")
    assert "--resume" not in fake.starts()[-1] and "fix the greeting" in fake.stdin()
    assert not kept.exists()  # (the session no turn goes on in is gone)
    transcript(fake.home, "sess-0002")
    assert chat.client.patch(f"/api/conversations/{chat.cid}",
                             json={"archived": True}, headers=OWN).status_code == 200
    assert chat.client.post("/api/conversations/delete",
                            json={"ids": [chat.cid]}, headers=OWN).json()["deleted"] == [chat.cid]
    assert not list(fake.home.glob("projects/*/*.jsonl"))  # (gone with its conversation)


@pytest.mark.parametrize("left", ["put_on_record", "note_handed_late", "question_answered"])
def test_what_its_session_never_saw_of_its_turn_starts_the_next_anew(chat, fake, left):
    # What KOLONİ puts before its last answer (`_history`) would not reach a resumed session.
    (lead,) = leads(chat)
    with chat.db() as session:
        said = session.query(Message.id).filter(Message.agent_id == lead.id).limit(1).scalar()
        if left == "put_on_record":  # (a write taken back, a keep card)
            session.add(ToolCall(run_id=lead.run_id, agent_id=lead.id, message_id=said,
                                 seq=99, provider_call_id="cli_x", name="write_file",
                                 arguments="{}", status="denied", result="taken back"))
        elif left == "note_handed_late":
            session.add(Message(conversation_id=chat.cid, run_id=lead.run_id, agent_id=lead.id,
                                role="agent", content="a late note",
                                created_at=now() - timedelta(hours=1), delivered_at=now()))
        else:  # (B-145: answered for the user, or another's)
            call = ToolCall(run_id=lead.run_id, agent_id=lead.id, message_id=said, seq=0,
                            provider_call_id="q", name="ask_user", arguments="{}")
            session.add(call)
            session.flush()
            session.add(Question(run_id=lead.run_id, agent_id=lead.id, tool_call_id=call.id,
                                 question="Fix the old ones?", options=[], status="answered",
                                 answer="Leave them", answered_at=now(), lead_why="done"))
        session.commit()
    chat("now the tests")
    assert "--resume" not in fake.starts()[-1] and "fix the greeting" in fake.stdin()


# --- Qoder, Codex, Copilot, agy (measured 5 Nov 2026: cli-surdurme-olcum.md) ---------------

NO_QODER_SESSION = [42, (Path(__file__).with_name("qoder_streams") / "no-session.txt").read_text(
    "utf-8").strip()]


@pytest.fixture
def qoder(tmp_path, fake, monkeypatch):
    """The fake stands in for qodercli on Claude Code's protocol, as in test_qoder_native - its
    resuming switched on, as it would be once it signs in from a home of KOLONİ's (it is off)."""
    monkeypatch.setattr(QoderNativeClient, "resumes", property(lambda self: True))

    def make(**more):
        cli = fake(version="1.1.51", **more)
        return QoderNativeClient(launcher=FAKE, model="Qwen3.8-Flash", timeout=30,
                                 env=dict(cli._env))
    return make


def test_qoders_next_turn_resumes_its_session_with_this_runs_leave(qoder, fake, tmp_path):
    cli = qoder()
    kept = run(cli, tmp_path, FIRST).session
    assert "--no-session-persistence" not in fake.starts()[0] and "home" not in kept
    result = run(cli, tmp_path, SECOND, session=kept, withheld=("write",))
    assert "-r" not in fake.starts()[-1]  # (another leave: anew)
    kept = result.session
    run(cli, tmp_path, [*SECOND, {"role": "assistant", "content": "Tested."},
                        {"role": "user", "content": "and the docs"}],
        session=kept, withheld=("write",))
    argv = fake.starts()[-1]
    assert argv[argv.index("-r") + 1] == "sess-0001" and "--resume" not in argv
    told = fake.stdin()
    assert "and the docs" in told and RESUMED in told and "fix the greeting" not in told
    # Its leave is this run's own line, as for a new session: asked first, the write off.
    assert argv[argv.index("--permission-mode") + 1] == "default"
    assert argv[argv.index("--permission-prompt-tool") + 1] == "stdio"
    withheld = [argv[i + 1] for i, one in enumerate(argv) if one == "--disallowed-tools"]
    assert "Write" in withheld and "Edit" in withheld


@pytest.mark.parametrize("change", ["level", "folder", "model"])
def test_qoder_in_another_folder_level_or_model_starts_anew(qoder, fake, tmp_path, change):
    kept = run(qoder(), tmp_path, FIRST).session
    other = tmp_path / "other"
    other.mkdir()
    cli = qoder()
    if change == "model":
        cli._model = "Qwen3.8-Max"
    run(cli, other if change == "folder" else tmp_path, SECOND, session=kept,
        level="ask" if change == "level" else "full_auto")
    assert "-r" not in fake.starts()[-1] and "fix the greeting" in fake.stdin()


def test_a_session_qoder_does_not_have_falls_back_once_and_is_counted_once(qoder, fake, tmp_path):
    first = run(qoder(), tmp_path, FIRST)
    result = run(qoder(sessions=(), no_session=NO_QODER_SESSION, session_id="sess-0002"),
                 tmp_path, SECOND, session=first.session)
    assert ["-r" in argv for argv in fake.starts()] == [False, True, False]
    assert "fix the greeting" in fake.stdin() and "now the tests" in fake.stdin()
    # (The new run's alone, as one run's: the one that failed counted nothing.)
    assert (result.input_tokens, result.output_tokens) == (first.input_tokens, first.output_tokens)
    assert result.session["id"] == "sess-0002"


def test_any_other_failure_of_a_resumed_qoder_is_a_failure(qoder, fake, tmp_path):
    kept = run(qoder(), tmp_path, FIRST).session
    with pytest.raises(OwnStop, match="No conversation found"):  # (Claude Code's words: not its)
        run(qoder(sessions=()), tmp_path, SECOND, session=kept)
    assert ["-r" in argv for argv in fake.starts()] == [False, True]


def test_qoder_keeps_no_session_while_its_resuming_is_off(fake, tmp_path):
    cli = QoderNativeClient(launcher=FAKE, model="Qwen3.8-Flash", timeout=30,
                            env=dict(fake(version="1.1.51")._env))
    assert not cli.resumes
    assert run(cli, tmp_path, FIRST).session is None
    assert "--no-session-persistence" in fake.starts()[-1]


def test_codex_copilot_and_agy_go_on_in_no_session():
    # (Codex's app-server and Copilot's headless resume are not measured; agy's never is.)
    for cli in (CodexNativeClient(), CopilotNativeClient(), AgyClient()):
        assert not cli.resumes
