"""K3: what KOLONİ keeps of an agent's or a model's reason - the Orchestrator's for a card
(`Question.lead_why`) and a To-do task (`po.lead_why`), a judge's sentence (`Command.judged["why"]`,
either judge) - is masked as the decision log masks what it shows, before the cut: a Bearer token,
a password in an address and a known secret split by a zero-width space are no longer kept plain."""

import json

import pytest

from app import backlog, judge, raw, risk_judge
from app.agent.cards import lead_pick
from app.masking import masked
from tests.test_team import SECRET

ZWSP = "​"
SAID = (
    f"use Authorization: Bearer abcdef0123456789ghijkl, https://me:hunter2pass@example.com/x and "
    f"{SECRET[:6]}{ZWSP}{SECRET[6:]}"
)


@pytest.fixture(autouse=True)
def known(monkeypatch):
    monkeypatch.setattr(raw, "_known", lambda fresh=False: raw.spellings([SECRET]))


def plain(text: str) -> bool:
    return any(one in text for one in ("abcdef0123456789ghijkl", "hunter2pass", SECRET, SECRET[:6]))


def test_masked_takes_out_what_nobody_sees_and_masks_by_shape_and_by_name():
    kept = masked(SAID)
    assert not plain(kept) and kept.count(raw.HIDDEN) == 3, kept


def test_each_kept_reason_comes_out_masked():
    kept = [
        lead_pick(json.dumps({"answer": "Yes", "why": SAID}), ["Yes", "No"])[1],
        backlog.lead_decided(json.dumps({"decisions": [{"task": 1, "add": True, "why": SAID}]}), 1)[
            1
        ][1],
        risk_judge.verdict(json.dumps({"verdict": "risky", "why": SAID}))["why"],
        judge.verdict(json.dumps({"verdict": "ask", "quote": "", "why": SAID}), {})["why"],
    ]
    for one in kept:
        assert one and not plain(one) and raw.HIDDEN in one, one


def test_masked_before_the_cut():
    # (a secret at the edge of the cut is masked whole first - not half of it kept plain)
    edge = "w" * (risk_judge.WHY_CHARS - 10) + " " + SECRET
    why = risk_judge.verdict(json.dumps({"verdict": "risky", "why": edge}))["why"]
    assert SECRET[:6] not in why
