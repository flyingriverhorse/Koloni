"""K-bilgi 7: as a learning the user clicked for ends, KOLONİ asks its guide a few questions made
from the guide itself, as Try it asks (no tools), and what it cannot answer from its pages - an
answer naming no page and line, or saying the documents lack it - is its "It does not know yet".
It spends from the learning's money limit; nothing is asked where that is spent, or where the price
is unknown and the learning made all its requests."""

import asyncio
import json
import shutil
from types import SimpleNamespace

from app import knowledge
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN
from tests.test_knowledge_page import PAY, READS, _learned, _pages, _pid

GUIDE = ("## Payments\n- pay(amount) · docs/pay.md · official\n"
         "## Refunds\n- refund(id) · docs/refund.md · official\n## Webhooks\n- none")


def test_a_clicked_learning_asks_its_guide_and_keeps_what_it_could_not_answer(make_client,
                                                                              project_dir):
    client, model = make_client({"Lead": [
        text(GUIDE),
        text("pay(amount) takes it (pages/0001.md:2)."),  # Payments: known
        text("Refunds are not in my documents."),  # Refunds: says it lacks it
        text("It takes a payment."),  # pay(amount): names no page and line
        text("refund(id) (pages/0002.md:2)."),  # refund(id): known
    ]})
    (project_dir / "docs").mkdir()
    (project_dir / "docs" / "pay.md").write_text("Payments: pay(amount) takes a payment.",
                                                 encoding="utf-8")
    (project_dir / "docs" / "refund.md").write_text("Refunds: refund(id) gives the money back.",
                                                    encoding="utf-8")
    pid = _pid(client, project_dir)
    row = client.post(f"/api/projects/{pid}/knowledge", headers=OWN,
                      json={"topic": "Pay", "sources": ["docs"]}).json()
    made = client.post("/api/roles", headers=OWN, json={
        "name": "Pay expert", "description": "", "tools": READS}).json()
    client.put(f"/api/knowledge/{row['id']}/roles/{made['id']}", json={"mode": "full"},
               headers=OWN)
    assert client.post(f"/api/knowledge/{row['id']}/learn", json={"project_id": pid},
                       headers=OWN).status_code == 202
    state = _learned(client, row["id"], pid)
    assert state["failed"] is None
    # Webhooks: no page has its words - not known, and not asked.
    assert state["learned"]["unknown"] == ["Refunds", "Webhooks", "pay(amount)"]
    asked = [call[-1]["content"] for call in model.calls[1:]]
    assert asked == [f"What do your documents say about {one}?"
                     for one in ("Payments", "Refunds", "pay(amount)", "refund(id)")]
    # Asked as Try it asks: the guide and the parts found, no tool.
    system = model.calls[1][0]["content"]
    assert "Here you have no tools" in system and "pages/0001.md:" in system
    assert all(tools is None or tools == [] for tools in model.tool_args[1:])


def _known(**more) -> dict:
    return {**PAY, "max_pages": 500, "max_usd": 0.5, "removed": [], "weekly": False,
            "learn_with": None, "search_answering": False, **more}


def _measure(project_dir, record: dict, price, made: int = 1,
             guide: str | None = None, tokens=(100, 10)) -> tuple[dict, list]:
    _pages(project_dir, {"0001.md": "The registry keeps models.\nModels have versions."},
           ["0001.md"])
    if guide is not None:
        (project_dir / ".koloni" / "knowledge" / "pay" / "guide.md").write_text(
            guide, encoding="utf-8")
    asked = []

    async def ask(messages):
        asked.append(messages)
        return "Versions (pages/0001.md:3).", SimpleNamespace(input_tokens=tokens[0],
                                                            output_tokens=tokens[1])

    return asyncio.run(knowledge.measure(str(project_dir), _known(), record, ask, price,
                                         made)), asked


PRICE = SimpleNamespace(input=1.0, output=5.0)
LEARNED = {"learned_at": "2026-11-01T00:00:00+00:00", "model": "Fake", "pages": [],
           "guide_from": 1, "parts": ["0001.md"], "sources": PAY["sources"]}


def test_the_questions_spend_from_the_learnings_money_and_its_cost_says_so(project_dir):
    record, asked = _measure(project_dir, {**LEARNED, "cost": {"amount": 0.1, "currency": "USD"}},
                             PRICE)
    assert len(asked) == 2 and record["unknown"] == []
    # 0.1 + two answers of 100 in and 10 out at 1 / 5 USD a million.
    assert record["cost"]["amount"] == round(0.1 + 2 * (100 + 50) / 1e6, 6)
    kept = json.loads((project_dir / ".koloni" / "knowledge" / "pay" / "learned.json"
                       ).read_text(encoding="utf-8"))
    assert kept["unknown"] == [] and kept["cost"] == record["cost"]


def test_nothing_is_asked_where_the_money_is_spent_or_not_known(project_dir):
    spent = {**LEARNED, "cost": {"amount": 0.5, "currency": "USD"}}
    for record, price, made in (
            (spent, PRICE, 1),  # its money limit spent by the learning
            ({**LEARNED, "cost": None}, PRICE, 1),  # what the learning spent is not known
            ({**LEARNED, "cost": None}, None, knowledge.CLICKED)):  # unknown price, at its cap
        kept = project_dir / ".koloni"
        shutil.rmtree(kept, ignore_errors=True)
        # (Its first question has no page: not known unasked - and nothing is written all the same.)
        after, asked = _measure(project_dir, record, price, made, guide=NO_PAGE_FIRST)
        assert asked == [] and after is record and "unknown" not in after
        assert "unknown" not in (project_dir / ".koloni" / "knowledge" / "pay" / "learned.json"
                                 ).read_text(encoding="utf-8")


NO_PAGE_FIRST = "## Webhooks\n## Registry\n- models have versions"


def test_money_that_runs_out_midway_is_counted_and_writes_no_part_as_the_whole(project_dir):
    # What is left pays for one answer (at most ~0.016 USD, as `_call` counts it; it spends 0.025),
    # not a second: the cost has it, `unknown` is not written.
    left = 0.03
    record, asked = _measure(project_dir, {**LEARNED, "cost": {"amount": 0.5 - left,
                                                               "currency": "USD"}}, PRICE,
                             guide=NO_PAGE_FIRST, tokens=(10_000, 3_000))
    assert len(asked) == 1 and "unknown" not in record
    assert record["cost"]["amount"] == round(0.5 - left + 0.025, 6)


def test_the_questions_come_from_the_guides_own_headings_spaced_through_it():
    guide = "\n".join(["## What it offers", "## Pitfalls"]
                      + [f"## Topic {n}\n- entry {n}" for n in range(10)]) + (
        "\n\n## Sections\n- abc.md: x")
    assert knowledge.questions(guide) == [f"Topic {n}" for n in (0, 2, 4, 6, 8)]
    # Few headings: its entries' words too, before their source.
    assert knowledge.questions("## What it offers\n- `pay(amount)` · docs/api.md · official") == [
        "pay(amount)"]


def test_an_answer_is_known_only_with_a_page_and_line_and_no_saying_it_lacks_it():
    assert knowledge.answered("Use it (pages/0003.md:12).")
    assert knowledge.answered("See 0003.md:12.")
    assert not knowledge.answered("Use pay(amount) (docs/api.md).")
    assert not knowledge.answered("The documents don't say (pages/0003.md:12 is about refunds).")
    assert not knowledge.answered("It is not in my documents.")


def test_on_an_unknown_price_the_request_cap_is_counted_before_each_question(project_dir):
    # One request left of the click's cap: one question asked, the second not - and no part
    # of the measure written as the whole.
    record, asked = _measure(project_dir, {**LEARNED, "cost": None}, None,
                             made=knowledge.CLICKED - 1)
    assert len(asked) == 1 and "unknown" not in record


def test_a_measure_that_breaks_fails_no_learning(make_client, project_dir, monkeypatch):
    async def broken(*_args, **_kwargs):
        raise RuntimeError("something unforeseen")

    monkeypatch.setattr(knowledge, "measure", broken)
    client, _model = make_client({"Lead": [text("## What it offers\n- pay(amount)")]})
    (project_dir / "docs").mkdir()
    (project_dir / "docs" / "api.md").write_text("pay(amount) takes a payment", encoding="utf-8")
    pid = _pid(client, project_dir)
    row = client.post(f"/api/projects/{pid}/knowledge", json=PAY, headers=OWN).json()
    made = client.post("/api/roles", headers=OWN, json={
        "name": "Pay expert", "description": "", "tools": READS}).json()
    client.put(f"/api/knowledge/{row['id']}/roles/{made['id']}", json={"mode": "full"},
               headers=OWN)
    assert client.post(f"/api/knowledge/{row['id']}/learn", json={"project_id": pid},
                       headers=OWN).status_code == 202
    state = _learned(client, row["id"], pid)
    assert state["failed"] is None and state["guide"] is not None
    assert state["learned"]["unknown"] is None
