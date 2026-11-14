"""What `app.knowledge.checked` keeps of each kind of source, and what it refuses, in its words.
Nothing is read and nothing leaves this machine: a name is never looked up here."""

import pytest

from app import knowledge


def kept(*sources: str) -> list[str]:
    return knowledge.checked({"topic": "Pay", "sources": list(sources)})["sources"]


def test_each_kind_of_source_is_kept_tidied_in_the_order_given_each_once():
    assert kept(" CODE: ") == ["code:"]
    assert kept(" Research:  card   payments ") == ["research: card payments"]
    assert kept("https://docs.example.com/pay", "docs\\api.md", "/docs/", "docs/api.md", "/") == [
        "https://docs.example.com/pay", "docs/api.md", "docs", "."]
    assert kept("repo: https://github.com/owner/name")[0].startswith("repo: https://github.com/")


def test_koloni_s_guide_is_kept_where_this_copy_has_its_docs(monkeypatch, tmp_path):
    assert kept(" Koloni-Guide: ") == ["koloni-guide:"]
    monkeypatch.setattr(knowledge, "KOLONI_DOCS", tmp_path / "none")
    with pytest.raises(ValueError, match=r"this copy of KOLONİ has no guide \(docs/\) to read"):
        kept("koloni-guide:")


@pytest.mark.parametrize("source, why", [
    ("Notes:", "notes: is written by KOLONİ, from what you accept at a turn's end"),
    ("research:", "research: needs a topic to search for, in at most"),
    ("http://127.0.0.1/x", "http://127.0.0.1/x: not reachable from here"),
    ("../out.md", "../out.md: not an http(s) address or a path in the project (docs/api.md)"),
    ("folder: C:/x", knowledge.NOT_BY_AGENT),
])
def test_a_source_that_cannot_be_kept_is_refused_with_why(source, why):
    with pytest.raises(ValueError) as refused:
        kept(source)
    assert str(refused.value).startswith(why)


def test_a_source_of_its_own_is_kept_with_no_other():
    with pytest.raises(ValueError, match="code: is a knowledge of its own"):
        kept("code:", "docs")
    with pytest.raises(ValueError, match="koloni-guide: is a knowledge of its own"):
        kept("koloni-guide:", "docs")
    # (the first source that is wrong is the one said)
    with pytest.raises(ValueError, match="notes: is written"):
        kept("docs", "notes:", "../out.md")
