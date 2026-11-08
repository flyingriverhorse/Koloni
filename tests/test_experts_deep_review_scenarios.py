"""K-uzman-derin, its review round: a learning nobody clicked writes at most `UNATTENDED` new
sections on an unknown price, and each of its requests is one of the turn's; a click at most
`CLICKED`, and none after the writing's time; a folder of many skipped files is not old at once; the
single request says what it left and keeps the sections; one slice answered empty blocks none of
the others. Contract: `tests/test_experts_deep_scenarios.py`.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app import knowledge, web
from tests.test_chat_flow import text
from tests.test_experts_deep_scenarios import FOLDER, PAGE, PRICE, deep, known, pages
from tests.test_experts_scenarios import EXPERT, MD, OPEN, READS, SITE, Site, read
from tests.test_knowledge_page import expert
from tests.test_spawn import begin, call, spawn, step

GUIDE = "## What it offers\n- x · docs/a.md · official"


def run(root, kept, ask, price=None, extend=True):
    async def go():
        knowledge.begin(str(root), kept)
        try:
            return await knowledge.learn(str(root), kept, ask, price, "Fake · fake-model",
                                         extend=extend)
        finally:
            knowledge.end(str(root), kept)

    return asyncio.run(go())


def counting(said=lambda messages: GUIDE, wait=0.0):
    asked: list[list[dict]] = []

    async def ask(messages):
        asked.append(messages)
        await asyncio.sleep(wait)
        return said(messages), SimpleNamespace(input_tokens=len(messages[1]["content"]) // 4,
                                               output_tokens=knowledge.GUIDE_TOKENS)

    return ask, asked


def test_nobody_clicked_writes_few_sections_on_an_unknown_price_even_after_a_click(
    monkeypatch, project_dir
):
    pages(monkeypatch, count=90)  # (eight slices)
    kept = known()
    record, _asked = deep(project_dir, kept)  # (a click: all eight)
    assert len(record["sections"]) == 8
    pages(monkeypatch, count=90, fill="v")  # (every slice changed)
    again, asked = deep(project_dir, kept, extend=False)
    assert len(asked) == knowledge.UNATTENDED + 1 and len(again["sections"]) == knowledge.UNATTENDED


def test_a_click_on_an_unknown_price_writes_at_most_its_cap_and_says_the_requests_left(
    monkeypatch, project_dir
):
    pages(monkeypatch, count=50)  # (five slices)
    monkeypatch.setattr(knowledge, "CLICKED", 2)
    record, asked = deep(project_dir, known())
    assert len(asked) == 3 and len(record["sections"]) == 2 and record["left"] > 0
    assert knowledge.requests(record) == 3  # (its three slices left, at most two, and the map)
    assert knowledge.requests(None) is None


def test_writing_stops_at_its_time_and_keeps_what_it_wrote(monkeypatch, project_dir):
    pages(monkeypatch, count=50)  # (five slices)
    # The clock it reads moves 100 s an answer, and only then: no real time is waited for.
    clock = [0.0]
    monkeypatch.setattr(knowledge, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(knowledge, "WRITING_SECONDS", 250)
    ask, asked = counting()

    async def slow(messages):
        clock[0] += 100
        return await ask(messages)

    record = run(project_dir, known(), slow)
    # At 300 s, past 250: three sections written, none started after; the map, and the rest left.
    assert len(record["sections"]) == 3 and record["left"] > 0 and len(asked) == 4


def test_a_folder_of_many_skipped_files_is_not_old_once_learned_and_none_is_read_again(
    monkeypatch, project_dir
):
    docs = project_dir / "docs"
    docs.mkdir()
    for n in range(10):
        (docs / f"t{n}.md").write_text(f"text {n}", encoding="utf-8")
    for n in range(knowledge.MAX_LOG + 5):
        (docs / f"b{n:03d}.bin").write_bytes(b"\x00\x01\x02" * 10)
    kept = known("docs")
    ask, _asked = counting()
    record = run(project_dir, kept, ask)
    assert len(record["skipped"]) == knowledge.MAX_LOG + 5  # (its log says MAX_LOG of them)

    def never(root, rel):
        raise AssertionError(f"{rel} read again")

    monkeypatch.setattr(knowledge, "_file", never)  # (by its name only, at every step)
    assert knowledge.stale(str(project_dir), kept) is None
    (docs / "t99.md").write_text("new", encoding="utf-8")  # (one with text: added)
    assert knowledge.stale(str(project_dir), kept) == "docs/t99.md was added since"


def test_a_folder_is_looked_into_as_far_as_its_cap_by_learning_and_stale_alike(
    monkeypatch, project_dir
):
    docs = project_dir / "docs"
    docs.mkdir()
    for n in range(10):
        (docs / f"t{n}.md").write_text(f"text {n}", encoding="utf-8")
    monkeypatch.setattr(knowledge, "MAX_WALK", 6)
    kept = known("docs")
    ask, _asked = counting()
    record = run(project_dir, kept, ask)
    assert 0 < len(read(record)) < 10 and knowledge.stale(str(project_dir), kept) is None


def test_a_limit_for_one_section_and_the_map_writes_one_section(monkeypatch, project_dir):
    pages(monkeypatch)
    ask, asked = counting()
    record = run(project_dir, known(max_usd=0.07), ask, PRICE)
    assert len(record["sections"]) == 1 and len(asked) == 1 and record["left"] == 18 * PAGE


def test_the_single_request_says_what_it_left_and_keeps_the_sections(monkeypatch, project_dir):
    pages(monkeypatch)
    kept = known()
    record, _asked = deep(project_dir, kept)  # (three sections)
    pages(monkeypatch, fill="v")  # (changed: none of them is this learning's)
    dear = SimpleNamespace(input=15.0, output=75.0, currency="USD")  # (one request at most)
    again, asked = deep(project_dir, kept, dear)
    assert len(asked) == 1 and again["sections"] == [] and again["left"] > 80_000
    # Learning again would pay for this same request: what one section and the map would cost.
    assert again["short"] == 0.9 and record["short"] is None
    for one in record["sections"]:  # (kept, for a learning on a cheaper model)
        assert (project_dir / FOLDER / one["file"]).exists()


def test_the_map_is_asked_only_where_the_money_limit_pays_for_it(monkeypatch, project_dir):
    pages(monkeypatch)
    ask, asked = counting(lambda messages: GUIDE + "\n" + "- z · docs/a.md · official\n" * 900)
    run(project_dir, known(), ask)  # (three long sections, on an unknown price)
    dear = SimpleNamespace(input=15.0, output=75.0, currency="USD")
    again = run(project_dir, known(max_usd=0.3), ask, dear)
    # Its sections as they are, and no map it cannot pay for: their openings stand for it.
    assert len(asked) == 4 and len(again["sections"]) == 3 and again["cost"]["amount"] == 0


def test_one_slice_answered_empty_blocks_none_of_the_others(monkeypatch, project_dir):
    pages(monkeypatch)
    kept = known()
    ask, asked = counting(lambda messages: "" if "page 15 " in messages[1]["content"] else GUIDE)
    record = run(project_dir, kept, ask)
    assert len(record["sections"]) == 2 and record["empty"] == 1 and record["left"] == 12 * PAGE
    assert "the model wrote nothing for 1 of its slices" in knowledge.said_of(record)
    # Again: the two written are kept, the empty one asked once more.
    again = run(project_dir, kept, ask)
    assert len(asked) == 4 + 2 and again["empty"] == 1  # (the empty one and the map)


def test_an_llms_full_txt_that_did_not_come_whole_gives_way_to_the_sites_pages(
    monkeypatch, project_dir
):
    Site(monkeypatch, {
        f"{SITE}/robots.txt": OPEN,
        f"{SITE}/pay/llms.txt": (200, "text/plain", "- [a](/pay/a)\n"),
        f"{SITE}/pay/a": (200, MD, "pay()"),
    })
    raw = web.raw

    async def cut(method, url, headers, body, ip):
        if url.endswith("llms-full.txt"):
            return web.Raw(200, {"content-type": "text/plain"}, b"the head of it", cut=True)
        return await raw(method, url, headers, body, ip)

    monkeypatch.setattr(web, "raw", cut)
    record, _asked = deep(project_dir, known())
    assert read(record) == [f"{SITE}/pay/a"]
    assert "did not come whole" in record["pages"][0]["why"]


def test_the_maps_request_holds_its_sections_headings_within_a_slice(monkeypatch, project_dir):
    Site(monkeypatch, {
        f"{SITE}/robots.txt": OPEN,
        f"{SITE}/pay/llms.txt": (200, "text/plain", "".join(
            f"- [p](/pay/{n})\n" for n in range(60))),
        **{f"{SITE}/pay/{n}": (200, MD, f"page {n} " + "w" * 59_000) for n in range(60)}})
    ask, asked = counting(lambda messages: "## What it offers\n" + "- y · docs/a.md · official\n"
                          * 2_000)
    run(project_dir, known(), ask)
    framing = len(web.framed("", knowledge.WHAT))
    assert len(asked[-1][1]["content"]) <= knowledge.MAX_GUIDE_INPUT + framing + 200


def test_each_request_of_a_learning_an_agent_asked_for_is_one_of_the_turns(
    make_client, wait_run, project_dir, monkeypatch
):
    real = web.Rate
    monkeypatch.setattr(web, "Rate", lambda most, seconds=60.0: real(min(most, 3), seconds))
    (project_dir / "docs").mkdir()
    for n in range(3):  # (three slices: three sections and the map, past three requests)
        (project_dir / "docs" / f"p{n}.md").write_text(f"page {n} " + "w" * 59_000,
                                                       encoding="utf-8")
    client, _model = make_client({
        "Lead": [spawn("Pay expert", "learn", "e"), text(GUIDE), text(GUIDE), text("done")],
        "Pay expert": [step(call("learn", {}, "l1")), text("not learned")],
    })
    expert(client, project_dir, {**EXPERT, "tools": READS, "knowledge": {
        **EXPERT["knowledge"], "sources": ["docs"]}})
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="ask the Pay expert to learn")
    snap = wait_run(client, cid, run_id)
    learned = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "l1")
    assert learned["status"] == "failed" and "30 requests a minute" in learned["result"]


def test_a_model_that_answers_nothing_is_asked_three_times_not_forty(monkeypatch, project_dir):
    pages(monkeypatch, count=60)  # (five slices)
    ask, asked = counting(lambda messages: "")
    with pytest.raises(knowledge.LearnError, match="wrote no guide"):
        run(project_dir, known(), ask)
    assert len(asked) == 3


def test_a_folders_walk_vets_the_project_once_a_listing_not_once_a_file(monkeypatch, project_dir):
    from app import project_files

    docs = project_dir / "docs"
    docs.mkdir()
    for n in range(50):
        (docs / f"t{n:02d}.md").write_text(f"text {n}", encoding="utf-8")
    kept = known("docs")
    ask, _asked = counting()
    run(project_dir, kept, ask)
    inside, counted = project_files._inside, []
    monkeypatch.setattr(project_files, "_inside", lambda root: counted.append(1) or inside(root))
    assert knowledge.stale(str(project_dir), kept) is None
    # The folder's listing and its path, its guide and its record read: not once a file of fifty.
    assert len(counted) <= 4
    secret = docs / ".env"
    secret.write_text("KEY=1", encoding="utf-8")
    assert "docs/.env" not in knowledge._walk(str(project_dir), "docs", 500)


def test_a_hand_written_skipped_list_of_no_names_is_none(project_dir):
    (project_dir / "api.md").write_text("pay()", encoding="utf-8")
    kept = known("api.md")
    ask, _asked = counting()
    run(project_dir, kept, ask)
    path = project_dir / FOLDER / "learned.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**record, "skipped": [{"a": 1}, ["b"], 3]}), encoding="utf-8")
    assert knowledge.stale(str(project_dir), kept) is None
