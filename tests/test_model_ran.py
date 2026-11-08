"""The model that really ran is on record, and "Only these models" is kept on every path."""

import json
import sys
from pathlib import Path

import pytest

from app.config import load_settings
from app.db.models import Provider
from app.main import create_app
from app.model_cli import ClaudeCliClient, CodexCliClient, codex_model
from app.model_client import ModelUnavailable
from app.model_native import ClaudeNativeClient, CodexNativeClient, CopilotNativeClient
from app.providers import NotListed, Providers, allowed
from tests.fakes import ScriptedModel
from tests.keyed import TestClient
from tests.test_chat_flow import text
from tests.test_discussion import discuss
from tests.test_spawn import begin, call, role_id, spawn, step
from tests.test_team import pick, results

# (What agents may pick is the user's to change, from the app's own page: slice 81a.)
OWN = {"Origin": "http://127.0.0.1:8790"}

STEP_CLI = [sys.executable, str(Path(__file__).with_name("fake_cli.py"))]
NATIVE_CLI = [sys.executable, str(Path(__file__).with_name("fake_codex_app_server.py"))]
HAIKU = "claude-haiku-4-5-20251001"
USED = {HAIKU: {"inputTokens": 3, "outputTokens": 12, "costUSD": 0.001}}


@pytest.fixture
def codex_home(tmp_path):
    home = tmp_path / "codex-settings"
    home.mkdir()
    return home


@pytest.fixture
def cli_app(settings_env, tmp_path):
    """An app with one more provider whose client is a real CLI client around a stand-in
    for the CLI. Returns (client, provider, started): `started()` says whether the
    stand-in was ever run."""
    opened = []
    record = tmp_path / "record.json"
    plan = tmp_path / "plan.json"

    def make(build, body, default_steps=(), env=None, **plan_fields):
        plan.write_text(json.dumps({"record": str(record), **plan_fields}), encoding="utf-8")
        cli = build(launcher=NATIVE_CLI if getattr(build, "native", False) else STEP_CLI,
                    timeout=30, env={"FAKE_CLI_PLAN": str(plan), **(env or {})})
        default = ScriptedModel(
            default_steps if isinstance(default_steps, dict) else list(default_steps),
            model_id="big-model")
        app = create_app(load_settings(settings_env), model=default, clients={body["name"]: cli})
        client = TestClient(app, base_url="http://127.0.0.1:8790")
        client.__enter__()
        opened.append(client)
        made = client.post("/api/providers", json=body)
        assert made.status_code == 201, made.text
        return client, made.json(), default

    make.started = record.exists
    make.pid = lambda: json.loads(record.read_text(encoding="utf-8"))["pid"]
    yield make
    for client in opened:
        client.__exit__(None, None, None)


def on(client, project_dir, provider, model=None, mode="full_auto", **more):
    """Start a turn of a conversation that uses this provider."""
    return begin(client, project_dir, mode=mode, provider_id=provider["id"], model_id=model,
                 **more)


async def one_step(client):
    async def on_delta(_text):
        pass

    return await client.stream_step("ignored", [{"role": "user", "content": "hi"}], None, on_delta)


# --- Claude Code, one step at a time ---------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("usage, expected", [
    (USED, HAIKU),
    # several models took part: the one that wrote the most is the one that answered
    ({"claude-haiku-4-5": {"outputTokens": 4}, "claude-opus-5": {"outputTokens": 90},
      "claude-sonnet-5": {"outputTokens": 9}}, "claude-opus-5"),
    ({}, None),
    (None, None),
    ("claude-opus", None),
    ({HAIKU: "not a count"}, HAIKU),
])
async def test_claude_names_the_model_that_answered_a_step(tmp_path, usage, expected):
    plan = tmp_path / "plan.json"
    fields = {} if usage is None else {"model_usage": usage}
    plan.write_text(json.dumps({"record": str(tmp_path / "record.json"), **fields}),
                    encoding="utf-8")
    client = ClaudeCliClient(launcher=STEP_CLI, timeout=20, env={"FAKE_CLI_PLAN": str(plan)})
    result = await one_step(client)
    assert result.content == "hello" and result.model == expected


def test_the_model_claude_reports_is_recorded_on_the_agent(cli_app, wait_run, project_dir):
    client, provider, _default = cli_app(
        ClaudeCliClient, {"name": "Claude", "kind": "claude_cli", "mode": "step"},
        model_usage=USED)
    cid, run_id = on(client, project_dir, provider)
    snap = wait_run(client, cid, run_id)
    agent = snap["agents"][0]
    assert (agent["status"], agent["model_id"], agent["model_from"]) == ("completed", HAIKU, None)
    assert snap["runs"][0]["model_id"] == HAIKU


def test_a_turn_on_a_message_keeps_the_name_the_cli_reported(
    cli_app, wait_run, project_dir, gate, tmp_path
):
    client, provider, default = cli_app(
        lambda **more: ClaudeCliClient(model="haiku", **more),
        {"name": "Claude", "kind": "claude_cli", "mode": "step"}, [
            spawn("Reviewer"),
            step(call("message_agent", {"to": "Reviewer", "message": "again"}, "m1")),
            gate.step(step(call("message_agent", {"to": "Reviewer", "message": "once more"}, "m2"))),
            text("done"),
        ], answer={"text": "looked", "tool_calls": []}, model_usage=USED)
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}",
                 json={"provider_id": provider["id"], "model_id": "haiku"})
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    gate.wait_partial()

    def reviewer():
        snap = client.get(f"/api/conversations/{cid}").json()
        return next(x for x in snap["agents"] if x["name"] == "Reviewer")

    # It ran, and carried on once: the name on record is the one the CLI gave both
    # times, not the short one KOLONİ asked for.
    assert (reviewer()["model_id"], reviewer()["model_from"]) == (HAIKU, None)
    named = [p["model_id"] for _id, kind, p in client.app.state.bus.replay(cid, 0)
             if kind == "agent.updated" and p["name"] == "Reviewer" and p["model_id"]]
    assert set(named) == {"haiku", HAIKU} and named.index(HAIKU) == named.count("haiku")
    # The next turn runs on another model, and says so: that is what is written.
    plan = tmp_path / "plan.json"
    told = json.loads(plan.read_text(encoding="utf-8"))
    plan.write_text(json.dumps(
        {**told, "model_usage": {"claude-haiku-5": {"outputTokens": 4}}}), encoding="utf-8")
    gate.release()
    snap = wait_run(client, cid, run_id, timeout=30)
    assert [t["status"] for t in snap["tool_calls"] if t["name"] == "message_agent"] == [
        "succeeded", "succeeded"]
    assert (reviewer()["model_id"], reviewer()["model_from"]) == ("claude-haiku-5", None)


def test_a_cli_that_names_no_model_leaves_it_unknown(cli_app, wait_run, project_dir):
    client, provider, _default = cli_app(
        ClaudeCliClient, {"name": "Claude", "kind": "claude_cli", "mode": "step"})
    cid, run_id = on(client, project_dir, provider)
    agent = wait_run(client, cid, run_id)["agents"][0]
    # Nothing is made up: this is what the page shows as "model not reported".
    assert (agent["status"], agent["model_id"], agent["model_from"]) == (
        "completed", "claude default", None)


# --- Codex: the model in its own settings ------------------------------------------------


def test_codex_settings_give_the_model_and_nothing_else_is_read(codex_home, monkeypatch):
    (codex_home / "config.toml").write_text(
        'model = "gpt-5.5-codex"\n[mcp_servers.x]\ncommand = "y"\n',
        encoding="utf-8")
    (codex_home / "auth.json").write_text('{"token": "never read"}', encoding="utf-8")
    read = []
    real = Path.read_text

    def spy(self, *args, **more):
        read.append(self.name)
        return real(self, *args, **more)

    monkeypatch.setattr(Path, "read_text", spy)
    assert codex_model({"CODEX_HOME": str(codex_home)}) == "gpt-5.5-codex"
    assert read == ["config.toml"]
    # without one of its own, the environment says where Codex keeps its settings
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    assert codex_model({}) == "gpt-5.5-codex"


@pytest.mark.parametrize("content", [
    None, "this is not [toml", "[profiles.x]\nmodel = 'inner'\n", "model = 5\n", 'model = ""\n',
    'model = "two\\nlines"\n', 'model = "' + "x" * 201 + '"\n',
])
def test_settings_that_cannot_be_read_leave_the_model_unknown(codex_home, content):
    if content is not None:
        (codex_home / "config.toml").write_text(content, encoding="utf-8")
    assert codex_model({"CODEX_HOME": str(codex_home)}) is None


@pytest.mark.anyio
async def test_only_codex_without_a_model_of_kolonis_takes_its_name_from_the_settings(
    codex_home,
):
    (codex_home / "config.toml").write_text('model = "gpt-5.5-codex"\n', encoding="utf-8")
    env = {"CODEX_HOME": str(codex_home)}
    for build in (CodexCliClient, CodexNativeClient):
        info = await build(launcher=["x"], env=env).info()
        assert (info.model_id, info.model_from) == ("gpt-5.5-codex", "settings")
        named = await build(model="o9", launcher=["x"], env=env).info()
        assert (named.model_id, named.model_from) == ("o9", None)
    # Codex's settings say nothing about another CLI's model
    for build, placeholder in ((ClaudeCliClient, "claude default"),
                               (ClaudeNativeClient, "claude default")):
        info = await build(launcher=["x"], env=env).info()
        assert (info.model_id, info.model_from) == (placeholder, None)
    # a native Codex speaking in a discussion is the same Codex
    spoken = await CodexNativeClient(launcher=["x"], env=env).talker().info()
    assert (spoken.model_id, spoken.model_from) == ("gpt-5.5-codex", "settings")
    copilot = await CopilotNativeClient(launcher=["x"], env=env).info()
    assert copilot.model_from is None and "gpt-5.5" not in copilot.model_id


def test_the_test_machines_own_codex_settings_are_out_of_reach():
    import os

    # tests/conftest.py points CODEX_HOME at a folder of the test's own
    assert "pytest" in os.environ["CODEX_HOME"] and codex_model({}) is None


@pytest.mark.parametrize("build, mode", [(CodexCliClient, "step"), (CodexNativeClient, "native")])
def test_an_agent_on_codexs_own_default_shows_the_settings_model(
    cli_app, wait_run, project_dir, codex_home, build, mode
):
    (codex_home / "config.toml").write_text('model = "gpt-5.5-codex"\n', encoding="utf-8")
    client, provider, _default = cli_app(
        build, {"name": "Codex", "kind": "codex_cli", "mode": mode},
        env={"CODEX_HOME": str(codex_home)}, script=[{"say": "Done."}])
    cid, run_id = on(client, project_dir, provider)
    snap = wait_run(client, cid, run_id, timeout=30)
    agent = snap["agents"][0]
    assert (agent["status"], agent["model_id"], agent["model_from"]) == (
        "completed", "gpt-5.5-codex", "settings")
    tested = client.post(f"/api/providers/{provider['id']}/test").json()
    assert (tested["model_id"], tested["model_from"]) == ("gpt-5.5-codex", "settings")


def test_a_real_run_from_the_models_page_says_which_model_answered(cli_app):
    client, provider, _default = cli_app(
        ClaudeCliClient, {"name": "Claude", "kind": "claude_cli", "mode": "step"},
        model_usage=USED, answer={"text": "ok", "tool_calls": []})
    found = client.post(f"/api/providers/{provider['id']}/test").json()
    assert (found["model_id"], found["reply"]) == ("claude default", None)
    assert not cli_app.started()
    tried = client.post(f"/api/providers/{provider['id']}/test?run=true").json()
    assert (tried["ok"], tried["reply"], tried["model_id"], tried["model_from"]) == (
        True, "ok", HAIKU, None)
    # K-56: the run is on Usage as "KOLONİ itself", under the model that answered
    used = client.get("/api/usage").json()
    assert [row["agents"] for row in used["by_start"] if row["started_by"] == "koloni"] == [1]
    assert [row["model_id"] for row in used["by_model"]] == [HAIKU]


# --- only these models ----------------------------------------------------------------

# What an agent is told of why: it names the setting, so the user reading it knows where.
LIMITED = (': the user limited it to listed models ("Never run a model that is not on this list", '
           'Models page)')
LISTED = {"models": [{"name": "haiku"}, {"name": "sonnet", "note": "slower"}],
          "only_listed": True}
CLAUDE = {"name": "Claude", "kind": "claude_cli", "mode": "step", **LISTED}


def test_what_is_allowed_is_the_list_and_nothing_else():
    def row(**more):
        return Provider(id="p", name="Claude", kind="claude_cli", **more)

    listed = [{"name": "haiku", "note": None}, {"name": "sonnet", "note": None}]
    allowed(row(models=listed), "opus")  # the box is not ticked: anything goes
    allowed(row(models=listed, only_listed=True), "haiku")
    for model in ("opus", "Haiku", "haiku ", None, ""):
        with pytest.raises(NotListed) as refused:
            allowed(row(models=listed, only_listed=True, default_model="opus"), model)
        assert "haiku, sonnet" in str(refused.value)
    assert isinstance(refused.value, ModelUnavailable)
    # two texts: the user is told of the setting, an agent only what it can do about it
    assert str(refused.value) == (
        "Claude runs only with the models listed for it (haiku, sonnet), and no model is "
        'chosen for it. Choose one of those, or switch "Never run a model that is not on this '
        'list" off on the Models page.')
    assert refused.value.to_agent == (
        f"Claude does not run here without a model chosen for it{LIMITED}. Only the user can "
        "change that.")
    with pytest.raises(NotListed) as refused:
        allowed(row(models=listed, only_listed=True, for_agents=True), 'op"us')
    assert refused.value.to_agent == (
        f'Claude does not run with the model "op\\"us" here{LIMITED}. The models that can be '
        'chosen on it: "haiku", "sonnet".')
    with pytest.raises(NotListed):
        allowed(row(models=None, only_listed=True), "haiku")


@pytest.mark.anyio
async def test_no_client_is_built_for_a_model_outside_the_list(settings):
    stand_in = ScriptedModel([text("never")])
    row = Provider(id="p", name="Claude", kind="claude_cli", only_listed=True,
                   models=[{"name": "haiku", "note": None}])
    for providers in (Providers(settings), Providers(settings, override=stand_in),
                      Providers(settings, named={"Claude": stand_in})):
        for model in ("opus", None):
            refused = providers.client(row, model)
            assert refused is not stand_in and not isinstance(refused, ClaudeCliClient)
            with pytest.raises(ModelUnavailable, match="haiku"):
                await refused.info()
            with pytest.raises(ModelUnavailable, match="haiku"):
                await one_step(refused)
        assert providers.client(row, "haiku") is not None
    assert stand_in.calls == []


@pytest.mark.parametrize("model, why", [
    ("opus", "opus is not one of them"), (None, "no model is chosen")])
def test_a_conversation_cannot_run_a_provider_outside_its_list(
    cli_app, wait_run, project_dir, model, why
):
    client, provider, _default = cli_app(ClaudeCliClient, CLAUDE)
    cid, run_id = on(client, project_dir, provider, model)
    snap = wait_run(client, cid, run_id)
    run = snap["runs"][0]
    assert run["status"] == "failed"
    assert why in run["error"] and "haiku, sonnet" in run["error"]
    assert "internal error" not in run["error"]
    assert not cli_app.started()  # no process was started


def test_a_listed_model_runs(cli_app, wait_run, project_dir):
    client, provider, _default = cli_app(ClaudeCliClient, CLAUDE)
    cid, run_id = on(client, project_dir, provider, "sonnet")
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"
    assert cli_app.started()


def test_the_default_model_is_held_to_the_list_too(cli_app, wait_run, project_dir):
    client, provider, _default = cli_app(ClaudeCliClient, {**CLAUDE, "default_model": "opus"})
    cid, run_id = on(client, project_dir, provider)
    run = wait_run(client, cid, run_id)["runs"][0]
    assert run["status"] == "failed" and "opus is not one of them" in run["error"]
    tested = client.post(f"/api/providers/{provider['id']}/test?run=true").json()
    assert tested["ok"] is False and "haiku, sonnet" in tested["error"]
    assert not cli_app.started()


def test_a_roles_model_outside_the_list_opens_no_sub_agent(cli_app, wait_run, project_dir):
    client, provider, default = cli_app(
        ClaudeCliClient, CLAUDE, [spawn("Coder"), text("did it myself")])
    client.patch(f"/api/roles/{role_id(client, 'Coder')}",
                 json={"provider_id": provider["id"], "model_id": "opus"})
    cid, run_id = begin(client, project_dir, mode="ask")
    snap = wait_run(client, cid, run_id)  # nobody was asked to approve it
    ((status, said),) = results(snap)
    # the agent is not told of a setting only the user sees, nor of models outside the guide
    assert (status, said) == (
        "failed",
        f'error: Claude does not run with the model "opus" here{LIMITED}. Only the user can '
        "change that.")
    assert len(snap["agents"]) == 1 and not cli_app.started()


def test_a_roles_model_outside_the_list_names_what_the_guide_lets_an_agent_choose(
    cli_app, wait_run, project_dir
):
    client, provider, default = cli_app(
        ClaudeCliClient, {**CLAUDE, "for_agents": True}, [spawn("Coder"), text("did it myself")])
    client.patch(f"/api/roles/{role_id(client, 'Coder')}",
                 json={"provider_id": provider["id"], "model_id": "opus"})
    cid, run_id = begin(client, project_dir, mode="ask")
    ((status, said),) = results(wait_run(client, cid, run_id))
    assert (status, said) == (
        "failed", f'error: Claude does not run with the model "opus" here{LIMITED}. The models '
        'that can be chosen on it: "haiku", "sonnet".')
    assert not cli_app.started()


def test_an_agents_pick_outside_the_list_opens_no_sub_agent(cli_app, wait_run, project_dir):
    client, provider, default = cli_app(
        ClaudeCliClient, {**CLAUDE, "for_agents": True, "default_model": "opus"},
        [step(pick("Reviewer", "Claude", id="a")), step(pick("Reviewer", "Claude", "opus", id="b")),
         text("did it myself")])
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    assert [status for status, _said in results(snap)] == ["failed", "failed"]
    # what it is told names the models that can be chosen, and no default that cannot run
    assert all('"haiku", "sonnet"' in said for _status, said in results(snap))
    assert not any("for its default" in said for _status, said in results(snap))
    assert len(snap["agents"]) == 1 and not cli_app.started()


def test_a_discussion_opens_no_member_outside_the_list(cli_app, wait_run, project_dir):
    client, provider, default = cli_app(
        ClaudeCliClient, CLAUDE, [discuss("hi or hello?", ["Reviewer"]), text("alone then")])
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}", json={"provider_id": provider["id"]})
    cid, run_id = begin(client, project_dir, mode="full_auto")
    snap = wait_run(client, cid, run_id)
    (talk,) = [t for t in snap["tool_calls"] if t["name"] == "discuss"]
    assert (talk["status"], talk["result"]) == (
        "failed", "error: no Reviewer can be opened: Claude does not run here without a model "
        f"chosen for it{LIMITED}. Only the user can change that.")
    assert len(snap["agents"]) == 1 and snap["discussions"] == []
    assert not cli_app.started()


def test_an_agent_is_not_carried_on_with_once_its_model_is_off_the_list(
    cli_app, wait_run, project_dir, gate
):
    client, provider, default = cli_app(
        ClaudeCliClient, {"name": "Claude", "kind": "claude_cli", "mode": "step"}, [
            spawn("Reviewer"),
            gate.step(step(call("message_agent", {"to": "Reviewer", "message": "again"}, "m1"))),
            text("done"),
        ], answer={"text": "looked", "tool_calls": []})
    client.patch(f"/api/roles/{role_id(client, 'Reviewer')}",
                 json={"provider_id": provider["id"], "model_id": "opus"})
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    gate.wait_partial()
    # The Reviewer has run once, on opus; now the user allows only haiku and sonnet.
    first_run = cli_app.pid()
    assert client.patch(f"/api/providers/{provider['id']}", headers=OWN, json=LISTED).status_code == 200
    gate.release()
    snap = wait_run(client, cid, run_id, timeout=30)
    (asked,) = [t for t in snap["tool_calls"] if t["name"] == "message_agent"]
    # the Lead is told it cannot be had, not how to change a setting of the user's; the
    # Reviewer's own record keeps the words for the user
    assert (asked["status"], asked["result"]) == (
        "failed",
        f'Reviewer could not reply: Claude does not run with the model "opus" here{LIMITED}. '
        "Only the user can change that.")
    reviewer = next(a for a in snap["agents"] if a["name"] == "Reviewer")
    assert "opus is not one of them" in (reviewer["error"] or "")
    assert cli_app.pid() == first_run  # the CLI was not run a second time




def test_codex_settings_with_a_profile_do_not_say_which_model_ran(tmp_path):
    from app.model_cli import codex_model

    (tmp_path / "config.toml").write_text(
        'model = "gpt-top"\nprofile = "work"\n[profiles.work]\nmodel = "gpt-work"\n',
        encoding="utf-8")
    assert codex_model({"CODEX_HOME": str(tmp_path)}) is None


def test_two_models_that_wrote_the_same_amount_are_not_guessed_between():
    import json as _json

    from app.model_cli import ClaudeCliClient

    out = _json.dumps({"type": "result", "modelUsage": {"a-model": {}, "b-model": {}}})
    assert ClaudeCliClient(None, None)._used(out) is None
    one = _json.dumps({"type": "result", "modelUsage": {
        "a-model": {"outputTokens": 3}, "b-model": {"outputTokens": 9}}})
    assert ClaudeCliClient(None, None)._used(one) == "b-model"


def test_a_turn_on_a_message_brings_a_name_nobody_reported_up_to_date(
    make_client, wait_run, project_dir
):
    from tests.fakes import ScriptedModel

    client, model = make_client({
        "Lead": [step(call("spawn_agent", {"role": "Reviewer", "task": "look"}, "s1")),
                 step(call("message_agent", {"to": "Reviewer", "message": "again"}, "m1")),
                 text("done")],
        "Reviewer": [text("looked"), text("looked again")],
    })

    class Served(ScriptedModel):
        """A model server that serves another model from the Lead's second step on."""

        @property
        def model_id(self):
            return "first-model" if len(self.calls) < 3 else "second-model"

        @model_id.setter
        def model_id(self, _name):
            pass

    model.__class__ = Served
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never")
    snap = wait_run(client, cid, run_id)
    assert snap["runs"][0]["status"] == "completed", snap["runs"][0]["error"]
    reviewer = next(a for a in snap["agents"] if a["name"] == "Reviewer")
    # its second turn ran on what the server serves now, and the record says so
    assert reviewer["model_id"] == "second-model"
