"""0.1.8 To-do in a chat, measured before it is written: the same three tasks done in three
chats, one after another in one chat, and in one chat with a topic each (a story each) - the
input tokens the lead is sent, side by side. The fake model's own counts are scripted, so the
measure is what KOLONİ sends it: every request of the lead's, at `_size` // CHARS_PER_TOKEN.

`flat` is also what one story of three tasks costs in its one topic: why a story's session
has a size past which a new one is opened."""

from app.agent.context_mixin import CHARS_PER_TOKEN
from app.agent.summary import _size
from tests.test_chat_flow import text
from tests.test_copilot_resume import chat  # noqa: F401  (a fixture)
from tests.test_spawn import call, step
from tests.test_topic_scenarios import setup, turn

ROWS = ("separate", "flat", "topics")
TASKS = (
    "TASK-ONE read big.txt and say what it holds",
    "TASK-TWO read big.txt again and count its lines",
    "TASK-THREE read big.txt once more and find its last line",
)
LAST = "BIG-LINE 099"  # its last line: the whole file reached the model
BIG = "".join(f"BIG-LINE {i:03d} " + "x" * 47 + "\n" for i in range(100))  # 6,000 characters


def tokens(request: list[dict]) -> int:
    return sum(_size(m) for m in request) // CHARS_PER_TOKEN


def lead_requests(make_client, wait_run, settings_env, tmp_path, how) -> list[list[list[dict]]]:
    """The lead's requests for each task, done `how`: each row an app, a database and a project
    of its own (same-length folder names: the path is in the system text)."""
    folder = tmp_path / f"r{ROWS.index(how)}"
    settings_env["KOLONI_RUNTIME_ROOT"] = str(folder / "runtime")  # (read as make_client makes)
    project = folder / "proj"
    project.mkdir(parents=True)
    (project / "big.txt").write_text(BIG, encoding="utf-8")
    read = step(call("read_file", {"path": "big.txt"}))
    client, model, pid, cid = setup(make_client, project, {"Lead": [read, text("done")] * 3})
    by_task = []
    for i, task in enumerate(TASKS):
        if how == "separate" and i:
            cid = client.post(f"/api/projects/{pid}/conversations").json()["id"]
            settings = {"permission_mode": "full_auto", "spawn_approval": "never"}
            assert client.patch(f"/api/conversations/{cid}", json=settings).status_code == 200
        before = len(model.calls_of.get("Lead", ()))
        snap, run = turn(client, wait_run, cid, task, new_topic=how == "topics")
        ended = next(r for r in snap["runs"] if r["id"] == run["id"])
        assert ended["status"] == "completed", (how, task, ended["error"])
        requests = model.calls_of["Lead"][before:]
        # (a request of KOLONİ's own - a title, the Scout - would be filed under the lead here)
        assert len(requests) == 2, (how, task, [str(r[0]["content"])[:80] for r in requests])
        assert LAST in requests[1][-1]["content"], (how, task, requests[1][-1])
        by_task.append(requests)
    assert model.by_agent == {"Lead": []}, (how, model.by_agent)
    return by_task


def table(sent: dict[str, list[int]], system: int, replayed: int) -> str:
    base = sum(sent["separate"])
    lines = [
        "",
        f"{'how':<10}{'task 1':>9}{'task 2':>9}{'task 3':>9}{'total':>9}{'x separate':>12}",
    ]
    for how, each in sent.items():
        cells = "".join(f"{n:>9}" for n in each)
        lines.append(f"{how:<10}{cells}{sum(each):>9}{sum(each) / base:>12.2f}")
    lines.append(
        f"(input tokens the lead is sent, {CHARS_PER_TOKEN} characters a token; its system "
        f"text alone {system} a request; big.txt's last line {replayed} times in flat's last)"
    )
    return "\n".join(lines)


def test_story_topics_cost_like_separate_chats(
    make_client, wait_run, settings_env, tmp_path, capsys
):
    done = {how: lead_requests(make_client, wait_run, settings_env, tmp_path, how) for how in ROWS}
    sent = {how: [sum(map(tokens, task)) for task in tasks] for how, tasks in done.items()}
    system = tokens([done["separate"][0][0][0]])
    replayed = str(done["flat"][2][1]).count(LAST)
    with capsys.disabled():
        print(table(sent, system, replayed))
    assert sum(sent["flat"]) > sum(sent["topics"]), sent
    assert sum(sent["flat"]) > sum(sent["separate"]), sent


def test_a_cli_going_on_in_its_session_is_handed_its_instructions_again(chat, capsys):
    """Native Copilot, which goes on in its own session within a topic: what KOLONİ hands it at
    a turn that goes on and at one of a new topic - not what its model reads, which is its whole
    session (the stand-in's counts are scripted)."""
    handed = {}
    for how, task in zip(("goes on", "new topic"), TASKS[1:], strict=True):
        chat(task, new_topic=how == "new topic")
        record = chat.record()
        assert ("resume" if how == "goes on" else "create") in record, (how, sorted(record))
        handed[how] = len(record["prompt"]) // CHARS_PER_TOKEN
    with capsys.disabled():
        print(f"\nhanded to the CLI's session at a turn, in tokens: {handed}")
    # (its instructions again at every turn that goes on: a story's session grows by them)
    assert handed["goes on"] >= handed["new topic"] * 0.9, handed
