"""Kanıtlı bitiş S11 (plan decisions 18, 19): the Fix rounds spent and a test still failing, the
fix is handed to the next stronger tier - fast, balanced, strongest - the same role on that
tier's model, each once a turn; its diagnosis first, read by its own line; failing work never
taken in. Scripted models by tier (`tiered`: Fast · quick is fast, Fast · deep balanced, Local ·
big-model strongest) and a scripted executor."""

import pytest

from app.agent import stronger_mixin as s11
from tests.fakes import ScriptedExecutor
from tests.test_agent_writes import write
from tests.test_chat_flow import text
from tests.test_proof_end_scenarios import OWN, PASS, failing
from tests.test_spawn import begin, step
from tests.test_team import team  # noqa: F401  (a fixture)
from tests.test_tier_scenarios import WHY, spawn, tiered

pytestmark = pytest.mark.no_po

CHECK = "python check.py"


def said(kind, why="the zero case is not handled", asked="May the total be zero?"):
    return text(f"Diagnosis: {kind} - {why}\nQuestion: {asked}")


def rows_of(snap, run_id):
    return [(r["kind"], r["state"], r["text"]) for m in snap["messages"]
            if m["role"] == "checked" and m["run_id"] == run_id for r in m["checked"]]


def started(team, project_dir, lead, fast, executor, approval="never", **project):  # noqa: F811
    client, _default, _quick = team(lead, fast, executor=executor)
    tiered(team, client)
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.patch(f"/api/projects/{pid}", json={
        "check_command": CHECK, "fix_rounds": 1, **project}, headers=OWN).status_code == 200
    cid, run_id = begin(client, project_dir, mode="full_auto",
                        **({"spawn_approval": approval} if approval else {}))
    return client, cid, run_id


FIRST = [step(spawn("Coder", "fast", WHY)), text("done"), text("done, as it is")]


def test_a_failing_turn_goes_up_the_tiers_until_it_passes(team, wait_run, project_dir):  # noqa: F811
    # (Each Coder's copy is taken in at Full auto after the check passes there; then the end
    # check fails on the project, twice, and passes after the strongest's round.)
    executor = ScriptedExecutor([PASS, failing(), PASS, failing(), PASS, PASS])
    client, cid, run_id = started(team, project_dir, {
        "Lead": FIRST, "Coder 4": [said(s11.FIX_INCOMPLETE)],
        "Coder 5": [step(write("a.py", "x = 3\n").tool_calls[0]), text("fixed the zero case")]},
        {"Coder": [step(write("a.py", "x = 1\n").tool_calls[0]), text("wrote it")],
         "Coder 2": [said(s11.FIX_INCOMPLETE)],
         "Coder 3": [step(write("a.py", "x = 2\n").tool_calls[0]), text("tried")]}, executor)
    snap = wait_run(client, cid, run_id, timeout=60)
    rows = rows_of(snap, run_id)
    texts = [one[2] for one in rows]
    # (The stand-in Fast model calls itself fast-model, whatever tier it was asked as.)
    assert s11.HANDED.format(model="deep", tier="Balanced", n="1 round", by="fast-model") in (
        texts), rows
    assert s11.HANDED.format(model="big-model", tier="Strongest", n="1 round",
                             by="fast-model and deep") in texts, rows
    assert ("tests", "passed") in [(k, st) for k, st, _t in rows], (rows, executor.started)
    assert not any(st == "failed" for _k, st, _t in rows), rows


ONE = [step(spawn("Coder", "balanced", WHY)), text("done"), text("done, as it is")]
WORK = {"Coder": [step(write("a.py", "x = 1\n").tool_calls[0]), text("wrote it")]}
ASKED = "please check my greeting"  # (`test_spawn.begin`'s request)


def one_tier(team, wait_run, project_dir, strongest, scripts, **project):  # noqa: F811
    """The work by the balanced model, the strongest one handed it: its rows and the run."""
    executor = ScriptedExecutor(scripts)
    client, cid, run_id = started(team, project_dir, {"Lead": ONE, **strongest}, WORK, executor,
                                  **project)
    snap = wait_run(client, cid, run_id, timeout=60)
    return [one[2] for one in rows_of(snap, run_id)], snap, executor


def test_test_wrong_with_the_requests_words_may_change_the_test(team, wait_run,  # noqa: F811
                                                                 project_dir):
    why = 'the request asks to "check my greeting", the test wants another'
    texts, _snap, _executor = one_tier(team, wait_run, project_dir, {
        "Coder 2": [said(s11.TEST_WRONG, why)],
        "Coder 3": [step(write("test_a.py", "def test_a(): pass\n").tool_calls[0]),
                    text("changed the test as the request asks")]},
        [PASS, failing(), PASS, PASS])
    assert s11.TEST_CHANGED.format(why=why) in texts, texts
    assert "Tests passed: python check.py - 4 passed in 0.1s" in texts, texts


def test_test_wrong_without_the_requests_words_is_fix_incomplete(team, wait_run,  # noqa: F811
                                                                  project_dir):
    texts, _snap, _executor = one_tier(team, wait_run, project_dir, {
        "Coder 2": [said(s11.TEST_WRONG, "the test is too strict")],
        "Coder 3": [step(write("a.py", "x = 2\n").tool_calls[0]), text("fixed")]},
        [PASS, failing(), PASS, PASS])
    assert s11.NOT_QUOTED.format(model="big-model") in texts, texts
    assert not any(one.startswith("Test changed") for one in texts), texts


def test_approach_wrong_in_the_project_goes_on_from_the_work(team, wait_run,  # noqa: F811
                                                              project_dir):
    texts, _snap, _executor = one_tier(team, wait_run, project_dir, {
        "Coder 2": [said(s11.APPROACH_WRONG, "a cache cannot pass this")],
        "Coder 3": [step(write("a.py", "x = 2\n").tool_calls[0]), text("did it another way")]},
        [PASS, failing(), PASS, failing()])
    assert s11.IN_PROJECT in texts, texts
    # (nothing passed: the failing line names every model that had rounds)
    assert s11.STILL_HANDED.format(by="fast-model and big-model") in texts, texts


def test_with_the_switch_off_no_stronger_model_is_handed_it(team, wait_run,  # noqa: F811
                                                             project_dir):
    texts, snap, _executor = one_tier(team, wait_run, project_dir, {}, [PASS, failing()],
                                      stronger_model=False)
    assert not any(one.startswith("Handed to") for one in texts), texts
    assert [a["name"] for a in snap["agents"]] == ["Lead", "Coder"]


def test_flaky_or_failing_before_is_not_handed_on(team, wait_run, project_dir,  # noqa: F811
                                                   monkeypatch):
    # (S7 tells them apart first: none of the failures is this turn's - nothing to hand on)
    from app.agent.before_mixin import BeforeMixin

    async def none_new(_self, _ctx, held, _failed):
        held.rows.append({"kind": "before", "state": "note", "text": "Flaky: test_a",
                          "command": None, "guessed": False, "started_at": None,
                          "counts": None})
        return []
    monkeypatch.setattr(BeforeMixin, "_proof_before", none_new)
    texts, snap, _executor = one_tier(team, wait_run, project_dir, {}, [PASS, failing()])
    assert not any(one.startswith("Handed to") for one in texts), texts
    assert [a["name"] for a in snap["agents"]] == ["Lead", "Coder"]


def test_an_away_job_whose_tests_still_fail_ends_not_taken_in(make_client, project_dir):
    # (decision 18: an Away job ends there - its work kept in its copy, its report says why)
    from tests.test_proof_end_scenarios import away_job, job_rows
    check = "import sys\nprint('FAILED test_x - no')\nprint('1 failed')\nsys.exit(1)\n"
    client, _pid, job = away_job(make_client, project_dir, "full_auto", check=check,
                                 check_command=CHECK, fix_rounds=1)
    _snap, rows = job_rows(client, job)
    held = [r for one in rows for r in one if r["kind"] == "not_taken"]
    assert held and held[0]["text"].startswith("Not taken in"), rows
    assert any(one.startswith("Not taken in") for one in job["checks"]), job
    assert (project_dir / "hello.py").read_bytes() == b"print('hi')\n"  # (never taken in)



def test_with_the_default_spawn_approval_the_hand_off_asks_nothing(team, wait_run,  # noqa: F811
                                                                   project_dir):
    # (KOLONİ's own hand-off is no pick of an agent's: no card at Full auto)
    executor = ScriptedExecutor([PASS, failing(), PASS, PASS])
    client, cid, run_id = started(team, project_dir, {
        "Lead": ONE, "Coder 2": [said(s11.FIX_INCOMPLETE)],
        "Coder 3": [step(write("a.py", "x = 3\n").tool_calls[0]), text("fixed")]}, WORK,
        executor, approval=None)
    snap = wait_run(client, cid, run_id, timeout=60)
    texts = [one[2] for one in rows_of(snap, run_id)]
    assert "Tests passed: python check.py - 4 passed in 0.1s" in texts, (texts, snap["agents"])


def test_approach_wrong_in_a_copy_starts_over_in_a_fresh_one(make_client, project_dir,
                                                             monkeypatch):
    # (decision 19: the copy's changes dropped, a fresh copy from the start state, only the short
    # note of what was tried - here an Away job's copy; the tier given, as `make_client` has none)
    from tests.test_agent_writes import edit
    from tests.test_away_scenarios import evening, go_away, looked_at, night
    from tests.test_backlog_auto import until
    from tests.test_proof_end_scenarios import ONE_JOB, job_rows

    monkeypatch.setattr(s11.StrongerMixin, "_stronger_tiers",
                        lambda _self, _ctx, _held, _first: ([("strongest", "Local", "big")], []))
    check = ("import sys\nok = 'bye' in open('hello.py').read()\n"
             "print('3 passed' if ok else '1 failed')\nsys.exit(0 if ok else 1)\n")
    (project_dir / "check.py").write_text(check, encoding="utf-8")
    client, _model, pid, cid, _run = evening(
        make_client, project_dir,
        [edit(), text("one done"), text("good morning"),
         said(s11.APPROACH_WRONG, "printing hello was never the way"),
         step(write("hello.py", "print('bye')\n", "wb").tool_calls[0]), text("did it another way")],
        mode="full_auto", plan=ONE_JOB, lead_work="itself", check_command=CHECK, fix_rounds=1)
    until(lambda: client.get(f"/api/conversations/{cid}").json()["runs"][0]["status"]
          == "completed")
    assert go_away(client, cid).status_code in (200, 201)
    job = until(lambda: (n := night(client, pid)) and looked_at(n) and n, seconds=30)["jobs"][0]
    snap, rows = job_rows(client, job)
    texts = [r["text"] for one in rows for r in one]
    assert s11.STARTED_OVER.format(why="printing hello was never the way") in texts, texts
    assert any(one.startswith("Tests passed") for one in texts), (texts, [(c["name"], c["status"], (c.get("result") or "")[:160]) for c in snap["tool_calls"]])
    # (the first approach's edit is no change of the work any more: dropped with its copy)
    assert [c["status"] for c in snap["file_changes"] if c["agent_id"] == snap["agents"][0]["id"]
            and c["path"] == "hello.py"][:1] == ["discarded"], snap["file_changes"]


def test_a_tier_over_its_limit_is_skipped_and_said(team, wait_run, project_dir,  # noqa: F811
                                                   monkeypatch):
    monkeypatch.setattr(s11, "over_limit",
                        lambda _session, provider: "over" if provider.name == "Local" else None)
    executor = ScriptedExecutor([PASS, failing(), PASS, PASS])
    client, cid, run_id = started(team, project_dir, {"Lead": FIRST}, {
        "Coder": [step(write("a.py", "x = 1\n").tool_calls[0]), text("wrote it")],
        "Coder 2": [said(s11.FIX_INCOMPLETE)],
        "Coder 3": [step(write("a.py", "x = 2\n").tool_calls[0]), text("fixed")]}, executor)
    snap = wait_run(client, cid, run_id, timeout=60)
    texts = [one[2] for one in rows_of(snap, run_id)]
    assert s11.SKIPPED.format(tier="Strongest", why=s11.OVER_ITS_LIMIT) in texts, texts
    assert not any("(Strongest)" in one for one in texts), texts
