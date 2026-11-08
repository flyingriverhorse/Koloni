"""KOLONİ's own guide as a knowledge (`knowledge.KOLONI_GUIDE`): the learner reads only the Markdown
of KOLONİ's docs/ - never its code, a secret or anything else of its checkout - into the project's
own folder; adding it learns nothing, and agents are never handed the folder."""

import subprocess
import sys

import pytest

from app import knowledge
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN
from tests.test_experts_scenarios import learn as learned_by
from tests.test_experts_work_scenarios import docs as project_docs
from tests.test_experts_work_scenarios import expert, offered_to, payments
from tests.test_knowledge_fresh import learn
from tests.test_parallel import until
from tests.test_recipe_run_scenarios import by_call, manual, recipe_named, row, strip
from tests.test_spawn import begin, spawn

GUIDE = {"topic": "KOLONİ guide", "sources": ["koloni-guide:"]}


@pytest.fixture
def docs(tmp_path, monkeypatch):
    """A stand-in for KOLONİ's checkout: docs/ with pages, a picture and a secret, and code
    and a .env beside it."""
    home = tmp_path / "koloni"
    (home / "docs" / "use").mkdir(parents=True)
    (home / "docs" / "index.md").write_text("# KOLONİ\nA chat beside a canvas.", encoding="utf-8")
    (home / "docs" / "use" / "chat.md").write_text(
        "**Summarise a long context at (%)** summarises the older part.", encoding="utf-8")
    (home / "docs" / "map.svg").write_text("<svg>not a page</svg>", encoding="utf-8")
    (home / "docs" / ".env").write_text("KEY=secret", encoding="utf-8")
    (home / "app.py").write_text("print('code')", encoding="utf-8")
    (home / ".env").write_text("KEY=secret", encoding="utf-8")
    monkeypatch.setattr(knowledge, "KOLONI_DOCS", home / "docs")
    return home / "docs"


def kept(**more):
    return knowledge.checked({**GUIDE, "max_pages": 20, "max_usd": 0.5, "learn_with": None, **more})


def test_its_source_is_its_own_and_names_no_path(docs):
    assert kept(sources=["Koloni-Guide:"])["sources"] == ["koloni-guide:"]
    with pytest.raises(ValueError, match="no other source"):
        kept(sources=["koloni-guide:", "docs"])
    # Anything after it is a path of the project, and a colon is none: nothing of KOLONİ's.
    for wider in ("koloni-guide:../app.py", "koloni-guide:/etc", "koloni-guide:" + chr(92) + ".env"):
        with pytest.raises(ValueError, match="not an http"):
            kept(sources=[wider])


def test_a_copy_without_docs_cannot_add_it(docs, monkeypatch):
    monkeypatch.setattr(knowledge, "KOLONI_DOCS", docs / "missing")
    with pytest.raises(ValueError, match="no guide"):
        kept()


def test_learning_reads_only_its_markdown_into_the_project(docs, project_dir):
    record, asked = learn(project_dir, kept())
    read = sorted(page["source"] for page in record["pages"] if page["read"])
    assert read == ["index.md", "use/chat.md"]
    sent = str(asked)
    assert "Summarise a long context at" in sent and "secret" not in sent and "print('code')" not in sent
    assert "<svg>" not in sent
    pages = project_dir / ".koloni" / "knowledge" / "koloni-guide" / "pages"
    assert len(list(pages.iterdir())) == 2
    # Fresh as learned; a page of the guide changed makes it old, by that page.
    assert knowledge.stale(str(project_dir), kept()) is None
    (docs / "use" / "chat.md").write_text("Changed.", encoding="utf-8")
    assert knowledge.stale(str(project_dir), kept()) == "use/chat.md changed since"


def test_adding_it_learns_nothing_and_learning_asks_for_a_model(client, project_dir, docs):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    added = client.post(f"/api/projects/{pid}/knowledge", json=GUIDE, headers=OWN)
    assert added.status_code == 201, added.text
    state = added.json()["state"]
    assert state["learning"] is False and state["learned"] is None
    assert state["stale"] == "no guide yet"
    assert not (project_dir / ".koloni" / "knowledge" / "koloni-guide").exists()
    # Learning starts only on the user's Learn - and, as for any knowledge, on a model chosen.
    learning = client.post(f"/api/knowledge/{added.json()['id']}/learn",
                           json={"project_id": pid}, headers=OWN)
    assert learning.status_code == 409 and "choose a model" in learning.text


def test_the_real_guide_is_read_through_the_project_readers_markdown_only():
    """Not stood in for: KOLONİ's own docs/, whose checkout is a place never opened, read as a root of
    its own - its pages, and nothing beside them."""
    read, _log, _left, _skipped = knowledge._files(str(knowledge.KOLONI_DOCS), ".", 500, None, ".md")
    names = [name for name, _text in read]
    assert "settings.md" in names and all(name.endswith(".md") for name in names)
    assert "Summarise a long context at" in dict(read)["settings.md"]


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is Windows' own")
def test_a_junction_inside_docs_is_not_followed(docs, tmp_path):
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "secret.md").write_text("never read", encoding="utf-8")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(docs / "linked"), str(tmp_path / "outside")],
                   check=True, capture_output=True)
    read, _log, _left, _skipped = knowledge._files(str(docs), ".", 500, None, ".md")
    assert sorted(name for name, _text in read) == ["index.md", "use/chat.md"]


def guide_expert(client, project_dir, teams=()):
    return expert(client, project_dir, "Guide expert", "koloni-guide:", teams)


def test_its_expert_is_not_given_learn_nor_told_to_learn(make_client, wait_run, project_dir):
    client, model = make_client({"Lead": [spawn("Guide expert", "what is Summarise a long context at?", "g1"),
                                          text("done")],
                                 "Guide expert": [text("I have not learned yet.")]})
    guide_expert(client, project_dir)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="ask the Guide expert")
    wait_run(client, cid, run_id)
    assert "learn" not in offered_to(model, "Guide expert")
    told = model.calls_of["Guide expert"][0][0]["content"]
    assert "You have no guide yet in this project: say you have not learned yet." in told
    assert "(learn)" not in told


def test_a_recipe_learn_step_does_not_open_it_however_old_its_guide(make_client, project_dir):
    """Its guide is old after each update of KOLONİ, and its expert cannot learn: a Learn step
    ("experts": "stale") opening it would pay for a turn that learns nothing."""
    project_docs(project_dir)
    client, _model = make_client({"Lead": [spawn("Guide expert", "learn", "p0"), text("so")]})
    team, pay = payments(client, project_dir)
    learned_by(project_dir, pay["knowledge"])
    guide_expert(client, project_dir, teams=[team["id"]])
    cid, _run_id = manual(client, project_dir, (team, recipe_named(client, "Integration")))
    snap = until(client, cid, lambda s: by_call(s) and by_call(s)[0][0] != "running")
    assert strip(row(snap))[:2] == [("learn", "skipped", 0), ("plan", "now", 0)]
    assert row(snap)["steps"][0]["unmet"] == "no expert's guide is to be learned"
