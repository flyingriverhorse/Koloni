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

from app.agent.review_mixin import ReviewMixin as _Review  # noqa: E402

REVIEW = _Review._proof_review  # (the real one: the shared setup turns it off here)

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
                                                                 project_dir, monkeypatch):
    from app.agent.review_mixin import ReviewMixin

    async def merges(_self, _ctx, held):  # (the Reviewer's fresh MERGE: the pass counts)
        held.verdict = "MERGE"
    monkeypatch.setattr(ReviewMixin, "_proof_review", merges)
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


def test_a_round_that_loosens_the_test_without_leave_is_no_pass(team, wait_run,  # noqa: F811
                                                                 project_dir):
    # (S11 review: under fix-incomplete the stronger model rewrote the failing test to pass)
    (project_dir / "test_a.py").write_text("def test_a():\n    assert 1 == 2\n", encoding="utf-8")
    texts, _snap, _executor = one_tier(team, wait_run, project_dir, {
        "Coder 2": [said(s11.FIX_INCOMPLETE)],
        "Coder 3": [step(write("test_a.py", "def test_a(): pass\n").tool_calls[0]),
                    text("fixed")]},
        [PASS, failing(), PASS, PASS])
    assert s11.TESTS_TOUCHED.format(model="big-model", paths="test_a.py") in texts, texts
    assert s11.STILL_HANDED.format(by="fast-model and big-model") in texts, texts
    # (each says it with the failing command: Fix it's, as a failing tests row's)
    rows = [r for m in _snap["messages"] if m["role"] == "checked" for r in m["checked"]
            if r["kind"] in ("stronger", "rounds") and r["state"] == "failed"]
    assert rows and all(r["command"] == CHECK for r in rows), rows


def test_a_test_wrong_round_is_read_by_the_reviewer(team, wait_run, project_dir,  # noqa: F811
                                                     monkeypatch):
    from app.agent.review_mixin import ReviewMixin
    seen = []

    async def recording(_self, _ctx, held):
        seen.append((len(held.handed), held.review_forced))
        held.verdict = "HOLD"  # (it holds the change)
        return None
    monkeypatch.setattr(ReviewMixin, "_proof_review", recording)
    why = 'the request asks to "check my greeting", the test wants another'
    texts, _snap, _executor = one_tier(team, wait_run, project_dir, {
        "Coder 2": [said(s11.TEST_WRONG, why)],
        "Coder 3": [step(write("test_a.py", "def test_a(): pass\n").tool_calls[0]),
                    text("changed the test as the request asks")]},
        [PASS, failing(), PASS, PASS])
    assert (1, True) in seen, (seen, texts)
    assert s11.TEST_HELD.format(model="big-model") in texts, texts


def test_s7s_failed_row_is_no_stronger_pass():
    from app import proof
    from app.agent.proof_mixin import Proof
    run = proof.TestRun(CHECK, ".", True)
    held = Proof()
    held.rows = [proof.row("tests", "passed", f"Tests passed: {CHECK} - 3 passed", CHECK),
                 proof.row("tests", "failed", "Fewer tests than the last green run: 3 of 4",
                           CHECK)]
    assert s11.StrongerMixin._handed_passed(held, [(run, "1 failed")]) is False


def test_held_fix_refuses_another_origin_a_made_up_merge_and_a_second_click(make_client,
                                                                            project_dir):
    from tests.test_proof_end_scenarios import away_job, job_rows
    check = "import sys\nprint('FAILED test_x - no')\nprint('1 failed')\nsys.exit(1)\n"
    client, _pid, job = away_job(make_client, project_dir, "full_auto", check=check,
                                 check_command=CHECK, fix_rounds=1)
    snap, _rows = job_rows(client, job)
    row, run_id = next((r, m["run_id"]) for m in snap["messages"] if m["role"] == "checked"
                       for r in m["checked"] if r["kind"] == "not_taken")
    body = {"merge_id": row["merge_id"], "reply": "the code"}
    url = f"/api/runs/{run_id}/held/fix"
    assert client.post(url, json=body, headers={"Origin": "http://evil.invalid"}).status_code == 403
    assert client.post(url, headers=OWN, json={**body, "merge_id": "x" * 32}).status_code == 409
    assert client.post(url, headers=OWN, json=body).status_code == 202
    assert client.post(url, headers=OWN, json=body).status_code == 409  # (on its way, or taken up)


WRONG = 'the request asks to "check my greeting", the test wants another'


@pytest.mark.parametrize("unread", ["failed", "no verdict", "over"])
def test_a_test_wrong_round_the_reviewer_did_not_read_is_no_pass(team, wait_run,  # noqa: F811
                                                                  project_dir, monkeypatch,
                                                                  unread):
    # (S11 re-check: the forced look failed open where the Reviewer could not look, gave no
    # verdict, or the turn was over its limit - the earlier verdict stood)
    from app.agent.review_mixin import Look, ReviewMixin
    monkeypatch.setattr(ReviewMixin, "_proof_review", REVIEW)
    look = Look("Reviewer", "x · y", None, None, "it failed" if unread == "failed" else None)

    async def no_look(_self, _ctx, _role, _task):
        return look
    monkeypatch.setattr(ReviewMixin, "_review_look", no_look)
    if unread == "over":  # (under the limit as it is handed on, over it by the forced look)
        calls = []
        monkeypatch.setattr(ReviewMixin, "_review_over",
                            lambda *_args: bool(calls.append(1)) or len(calls) > 1)
    texts, _snap, _executor = one_tier(team, wait_run, project_dir, {
        "Coder 2": [said(s11.TEST_WRONG, WRONG)],
        "Coder 3": [step(write("test_a.py", "def test_a(): pass\n").tool_calls[0]),
                    text("changed the test as the request asks")]},
        [PASS, failing(), PASS, PASS])
    assert any(one.startswith("Not a pass: the Reviewer did not read big-model") for one in texts), (
        texts)


def test_a_conftest_that_deselects_the_test_is_a_test_change(team, wait_run,  # noqa: F811
                                                              project_dir):
    texts, _snap, _executor = one_tier(team, wait_run, project_dir, {
        "Coder 2": [said(s11.FIX_INCOMPLETE)],
        "Coder 3": [step(write("conftest.py", "collect_ignore = ['test_a.py']\n").tool_calls[0]),
                    text("fixed")]},
        [PASS, failing(), PASS, PASS])
    assert s11.TESTS_TOUCHED.format(model="big-model", paths="conftest.py") in texts, texts


@pytest.mark.parametrize("path", ["conftest.py", "tests/conftest.py", "pytest.ini", "tox.ini",
                                  ".pytest.ini", "pytest.toml", ".pytest.toml",
                                  "vitest.workspace.ts",
                                  "setup.cfg", "pyproject.toml", "noxfile.py", "package.json",
                                  "vitest.config.ts", "vite.config.mts", "jest.config.js",
                                  "karma.conf.js", ".mocharc.yml", "playwright.config.ts"])
def test_what_steers_the_tests_is_a_test_change(path):
    assert s11.steers_tests(path) and not s11.steers_tests("src/config.py")
