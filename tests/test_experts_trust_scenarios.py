"""K-uzman, part 2: how far an expert's guide is to be trusted.

Contract:
- Each entry of a guide is a line "- <what> · <source> · <label>". The label is the model's, of a
  fixed list - official, single source, unsure - and code holds what it can: a label not of the
  list, a source none of the documents read (or none), or a conflict is unsure; official from no
  source of the makers' own (a site the user gave, a file of the project, the library's home or
  repository as its installed copy says) is single source. Nothing is "tried": running a
  guide's examples was left out on purpose (it needs an isolated sandbox).
- The expert names the label of what its answer rests on, and tells the one who asked to try an
  unsure one first.
"""

import asyncio
import json

from app import knowledge
from tests.test_experts_research_scenarios import searcher
from tests.test_experts_scenarios import EXPERT, MD, OPEN, SITE, Site, asker, known, learn
from tests.test_knowledge_page import expert

OTHER = "https://blog.test"


def entries(root):
    text = (root / ".koloni" / "knowledge" / "pay" / "guide.md").read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.startswith("- ")]


def pay_site(monkeypatch):
    return Site(monkeypatch, {
        f"{SITE}/robots.txt": OPEN,
        f"{SITE}/pay/llms.txt": (200, "text/plain", "- [a](/pay/a)\n"),
        f"{SITE}/pay/a": (200, MD, "pay(amount) takes a payment"),
        f"{OTHER}/robots.txt": OPEN,
        f"{OTHER}/post": (200, MD, "pay() is quick"),
    })


def test_a_label_is_held_to_the_list_the_documents_read_and_a_conflict(monkeypatch, project_dir):
    pay_site(monkeypatch)
    said = "\n".join([
        "## What it offers",
        f"- pay(amount) takes a payment · {SITE}/pay/a/ · official",
        f"- pay() is free · {SITE}/pay/a · surely",
        "- refund() undoes one · https://made.up/page · single source",
        "- amounts are in cents",
        f"- conflict: pay() takes cents, or euros · {SITE}/pay/a#top · official",
        "```python",
        "- not an entry, a line of code · x · official",
        "```",
    ])
    record, _asked = learn(project_dir, known(), said=said)
    assert entries(project_dir)[:5] == [
        # A site the user gave is its makers' own: official stays.
        f"- pay(amount) takes a payment · {SITE}/pay/a/ · official",
        "- pay() is free · " + f"{SITE}/pay/a · unsure",
        "- refund() undoes one · https://made.up/page · unsure",
        "- amounts are in cents · no source · unsure",
        f"- conflict: pay() takes cents, or euros · {SITE}/pay/a#top · unsure",
    ]
    text = (project_dir / ".koloni" / "knowledge" / "pay" / "guide.md").read_text(encoding="utf-8")
    assert "- not an entry, a line of code · x · official" in text
    assert record["labels"] == {"official": 1, "single source": 0, "unsure": 4}


def kept_with(project_dir, kept, said, added):
    ask, _asked = asker(said)

    async def run():
        knowledge.begin(str(project_dir), kept)
        try:
            return await knowledge.learn(str(project_dir), kept, ask, None, "F", added=added)
        finally:
            knowledge.end(str(project_dir), kept)

    return asyncio.run(run())


def test_what_was_found_while_answering_is_a_single_source_whatever_it_is_called(
    monkeypatch, project_dir
):
    Site(monkeypatch, {"https://docs.stripe.com/robots.txt": OPEN,
                       "https://docs.stripe.com/pay": (200, MD, "pay()")})
    kept = known("https://docs.stripe.com/pay")
    record = kept_with(project_dir, kept, "- pay() · https://docs.stripe.com/pay · official", [
        {"text": "refunds take 5 days", "source": "https://docs.stripe.com/anything",
         "label": "official"}])
    # Nothing of it was fetched: on the user's own site still one search's word.
    assert entries(project_dir) == [
        "- pay() · https://docs.stripe.com/pay · official",
        "- refunds take 5 days · https://docs.stripe.com/anything · single source"]
    assert record["labels"] == {"official": 1, "single source": 1, "unsure": 0}
    # Nor does it make its address a document read: the model citing it is not official.
    kept_with(project_dir, kept, "- refunds · https://docs.stripe.com/anything · official", [])
    assert entries(project_dir)[0] == "- refunds · https://docs.stripe.com/anything · unsure"


def test_a_code_block_left_open_ends_before_what_was_kept_and_tried_is_no_label(project_dir):
    (project_dir / "api.md").write_text("pay()", encoding="utf-8")
    record = kept_with(project_dir, known("api.md"), "\n".join([
        "- pay() · api.md · tried", "```python", "print(1)"]), [
        {"text": "it is safe", "source": "https://evil.example/x", "label": "tried"}])
    text = knowledge.guide(str(project_dir), known("api.md")).strip()
    assert text.splitlines()[:4] == ["- pay() · api.md · unsure", "```python", "print(1)", "```"]
    assert text.endswith("- it is safe · https://evil.example/x · single source")
    assert record["labels"] == {"official": 0, "single source": 1, "unsure": 1}


def test_official_is_under_the_address_given_not_anywhere_on_its_site(project_dir):
    official = knowledge._official(str(project_dir), {"topic": "Bar",
                                                      "sources": ["https://github.com/foo/bar"]})
    assert official("https://github.com/foo/bar/blob/main/README.md")
    assert not official("https://github.com/attacker/x")
    # A repository's issues, pull requests and discussions are anyone's words.
    assert not official("https://github.com/foo/bar/issues/1")
    assert not official("https://github.com/foo/bar/pull/2")
    assert not official("https://github.com/foo/bar/discussions/3")


def researched(project_dir, said, search):
    ask, _asked = asker(said)
    kept = known("research: pay")

    async def run():
        knowledge.begin(str(project_dir), kept)
        try:
            return await knowledge.learn(str(project_dir), kept, ask, None, "Fake · fake", search)
        finally:
            knowledge.end(str(project_dir), kept)

    return asyncio.run(run())


def test_official_from_a_site_nobody_named_its_makers_is_a_single_source(monkeypatch,
                                                                         project_dir):
    pay_site(monkeypatch)
    search, _asked = searcher(f"{OTHER}/post", f"{SITE}/pay/a")
    record = researched(project_dir, "\n".join([
        f"- pay() is quick · {OTHER}/post · official",
        f"- pay(amount) takes a payment · {SITE}/pay/a · official",
    ]), search)
    assert entries(project_dir) == [f"- pay() is quick · {OTHER}/post · single source",
                                    f"- pay(amount) takes a payment · {SITE}/pay/a · single source"]
    assert record["labels"]["single source"] == 2
    # The library's installed copy says where it is made: its pages are its makers' own.
    package = project_dir / "node_modules" / "pay"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({
        "name": "pay", "homepage": f"{SITE}/pay#readme",
        "repository": {"url": "git+https://github.test/pay/pay.git"}}), encoding="utf-8")
    researched(project_dir, f"- pay(amount) takes a payment · {SITE}/pay/a · official", search)
    assert entries(project_dir) == [f"- pay(amount) takes a payment · {SITE}/pay/a · official"]


def test_a_python_librarys_metadata_names_its_home_too(project_dir):
    meta = project_dir / ".venv" / "Lib" / "site-packages" / "pay_kit-1.2.dist-info"
    meta.mkdir(parents=True)
    (meta / "METADATA").write_text("Name: pay-kit\nHome-page: https://pay.test\n"
                                   "Project-URL: Source, https://github.test/pay/kit\n",
                                   encoding="utf-8")
    official = knowledge._official(str(project_dir), {"topic": "Pay-Kit", "sources": []})
    assert official("https://pay.test/docs") and official("https://github.test/pay/kit/x")
    assert not official("https://github.test/someone/else")
    # A file of the project the user gave is theirs to trust.
    assert official("docs/api.md")


def test_the_expert_names_the_label_and_has_an_unsure_one_tried(project_dir):
    told = knowledge.brief(str(project_dir), known("docs/api.md"))
    assert "the label of the guide's entry it rests on" in told
    assert "for unsure, tell the one who asked to try it before relying on it" in told
    assert "\"- <what it says> · <its source> · <label>\"" in knowledge.GUIDE_ASKED


# --- the version the documents are of ----------------------------------------------------------


def test_the_projects_version_of_the_library_is_read_off_its_manifest(project_dir):
    assert knowledge.project_version(str(project_dir), "Pay") is None
    (project_dir / "requirements.txt").write_text("# pinned\nPay_Kit==3.1 ; python_version>'3'\n",
                                                  encoding="utf-8")
    assert knowledge.project_version(str(project_dir), "pay-kit") == "3.1"
    (project_dir / "pyproject.toml").write_text(
        '[project]\nname = "app"\ndependencies = ["pay.kit[async]>=2.0,<3"]\n', encoding="utf-8")
    assert knowledge.project_version(str(project_dir), "Pay-Kit") == "2.0"
    (project_dir / "package.json").write_text(json.dumps(
        {"devDependencies": {"Pay": "^1.4.2"}}), encoding="utf-8")
    assert knowledge.project_version(str(project_dir), "pay") == "1.4.2"


def test_the_documents_version_is_what_most_of_their_addresses_say():
    assert knowledge.docs_version([f"{SITE}/v2/a", f"{SITE}/docs/v2.1/b", f"{SITE}/v1/c",
                                   "docs/v9/file.md", f"{SITE}/vue/d"]) == "2"
    assert knowledge.docs_version([f"{SITE}/pay/a"]) is None


def test_documents_of_another_major_version_are_warned_of(monkeypatch, project_dir, client):
    Site(monkeypatch, {
        f"{SITE}/robots.txt": OPEN,
        f"{SITE}/pay/llms.txt": (200, "text/plain", "- [a](/pay/v2/a)\n- [b](/pay/v2/b)\n"),
        f"{SITE}/pay/v2/a": (200, MD, "pay(amount)"), f"{SITE}/pay/v2/b": (200, MD, "refund()"),
    })
    (project_dir / "package.json").write_text(json.dumps({"dependencies": {"pay": "~1.4.2"}}),
                                              encoding="utf-8")
    record, _asked = learn(project_dir, known())
    assert record["version"] == {"project": "1.4.2", "docs": "2"}
    assert knowledge.version_warning(record) == "docs are for v2, the project has v1.4.2"
    assert "Its docs are for v2, the project has v1.4.2: say so with each answer" in (
        knowledge.brief(str(project_dir), known()))
    assert knowledge.version_warning({"version": {"project": "2.3", "docs": "2"}}) is None
    # On its Knowledge tab too.
    role = expert(client, project_dir, {**EXPERT, "knowledge": {
        "topic": "Pay", "sources": [f"{SITE}/pay"]}})
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    state = client.get(f"/api/roles/{role['id']}/knowledge", params={"project_id": pid}).json()
    assert state["version_warning"] == "docs are for v2, the project has v1.4.2"


def test_an_examples_source_on_a_line_of_its_own_is_its_entrys_not_a_second_label():
    # B-131 (live): the guide's examples said "· no source · unsure", then their sourced line.
    page = f"{SITE}/pay/a"
    guide, counts = knowledge.labelled("\n".join([
        "## Short examples", "- Take a payment", "```python", "pay(5)", "```", f"  · {page} · official",
        "## Pitfalls", "- amounts are in cents", "## More", f"· {page} · official"]), {page}, lambda s: True)
    assert guide.splitlines() == [
        "## Short examples", f"- Take a payment · {page} · official", "```python", "pay(5)", "```",
        "## Pitfalls", "- amounts are in cents · no source · unsure", "## More", f"· {page} · official"]
    assert counts == {"official": 1, "single source": 0, "unsure": 1}


def test_a_comment_in_an_examples_code_keeps_its_source_line_its_entrys():
    # (The review's nit: "# ..." in a code block was taken for a heading.)
    page = f"{SITE}/pay/a"
    guide, _counts = knowledge.labelled("\n".join([
        "- Take a payment", "```python", "# five cents", "pay(5)", "```", f"· {page} · official"]), {page}, lambda s: True)
    assert guide.splitlines()[0] == f"- Take a payment · {page} · official"
