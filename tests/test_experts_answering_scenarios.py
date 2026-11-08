"""K-uzman, part 2: an expert that searches the web while it answers, and what it found kept.

Contract:
- Off by default. Where the user switched "May search while answering" on, an expert under an
  opener that searches has web_search - at its work and answering a message - through the agents'
  own web tool: asked as any search is, and in a turn nobody watches only where the trigger lets
  it search. Its answer gives the address and ends with "Add this to the guide?".
- What the user or the Lead said yes to is passed to learn's add: kept in the guide, at every
  learning from then on, its label held as the guide's are.

No test touches the network: the search is stood in for.
"""

import asyncio

import pytest

from app import knowledge
from tests.test_chat_flow import text
from tests.test_chat_teams_scenarios import OWN
from tests.test_experts_research_scenarios import fake_search
from tests.test_experts_scenarios import EXPERT, asker, known
from tests.test_experts_scenarios import learn as learned_from
from tests.test_experts_work_scenarios import docs, offered_to
from tests.test_knowledge_page import expert
from tests.test_parallel import until
from tests.test_recipe_run_scenarios import answer, asked
from tests.test_spawn import begin, call, spawn, step
from tests.test_trigger_scenarios import NOBODY, run_now, trigger
from tests.test_web_tool_scenarios import setup

FOUND = "https://a.test/hooks/retry"
SEARCHING = {**EXPERT, "knowledge": {**EXPERT["knowledge"], "search_answering": True}}


def asked_by_the_coder(expert_steps):
    return {
        "Lead": [spawn("Pay expert", "be ready", "e1"), spawn("Coder", "build it", "c1"),
                 text("done")],
        "Pay expert": [text("ready"), *expert_steps],
        "Coder": [step(call("message_agent", {"to": "Pay expert",
                                              "message": "how long are webhooks retried?"}, "m1")),
                  text("built")],
    }


SEARCH = step(call("web_search", {"query": "pay webhook retries"}, "w1"))
ANSWER = text(f"3 days ({FOUND}, single source). Add this to the guide?")


def test_an_expert_searches_while_answering_only_where_the_user_switched_it_on(
    make_client, wait_run, project_dir, monkeypatch
):
    searched = fake_search(monkeypatch, FOUND)
    docs(project_dir)
    client, model = make_client(asked_by_the_coder([SEARCH, ANSWER]))
    expert(client, project_dir, EXPERT)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="have the Coder ask the Pay expert")
    snap = wait_run(client, cid, run_id)
    off = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "w1")
    assert off["status"] == "failed" and "not available" in off["result"] and searched == []
    assert "web_search" not in offered_to(model, "Pay expert")


def test_switched_on_it_searches_answering_and_asks_to_add_what_it_found(
    make_client, wait_run, project_dir, monkeypatch
):
    searched = fake_search(monkeypatch, FOUND)
    docs(project_dir)
    client, model = make_client(asked_by_the_coder([SEARCH, ANSWER]))
    role = expert(client, project_dir, SEARCHING)
    assert role["knowledge"]["search_answering"] is True
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never",
                        content="have the Coder ask the Pay expert")
    # An expert's search is asked below Full auto whatever the rules - and remembered for none.
    # (At Full auto it is not, K-fullauto-sorma 2: the test after this one.)
    snap = until(client, cid, lambda s: [w["status"] for w in s["web_requests"]] == ["proposed"])
    assert searched == [] and snap["web_requests"][0]["target"] == "pay webhook retries"
    assert client.post(f"/api/web-requests/{snap['web_requests'][0]['id']}/approve",
                       json={"remember": False}, headers=OWN).status_code == 200
    # B-134 (live): its "Add this to the guide?" never reached the user - the Lead said "you did
    # not ask, so it was not added". KOLONİ asks, and the user's word is its opener's and the Lead's.
    card = asked(until(client, cid, asked))
    assert card["question"].startswith("Pay expert found it on the web: Add this to the guide?")
    assert card["options"] == ["Add", "Not now"]
    answer(client, card, "Add")
    snap = wait_run(client, cid, run_id)
    word = {"role": "user", "content": "The user answered KOLONİ's card (Pay expert: Add this to the guide?): Add"}
    assert word in model.calls_of["Coder"][1] and word in model.calls_of["Lead"][2]
    by_id = {t["provider_call_id"]: t for t in snap["tool_calls"]}
    assert by_id["w1"]["status"] == "succeeded", by_id["w1"]["result"]
    assert FOUND in by_id["w1"]["result"]
    # Never the search the Anthropic API makes and is paid for.
    assert searched == [{"query": "pay webhook retries", "paid": False}]
    assert "Add this to the guide?" in by_id["m1"]["result"]
    told = model.calls_of["Pay expert"][0][0]["content"]
    assert "each search costs" in told and "end your answer with: Add this to the guide?" in told


def test_at_full_auto_the_search_is_not_asked_and_the_lead_answers_add_this_to_the_guide(
    make_client, wait_run, project_dir, monkeypatch
):
    """K-fullauto-sorma 2: no money in it (`paid=False`), so no card at Full auto; the "Add this
    to the guide?" card is the Lead's there, its word said to the Coder and the Lead as such."""
    from tests.test_lead_decides import says
    searched = fake_search(monkeypatch, FOUND)
    docs(project_dir)
    script = asked_by_the_coder([SEARCH, ANSWER])
    script["Lead"] = [spawn("Pay expert", "be ready", "e1"), spawn("Coder", "build it", "c1"),
                      says("Add", "A fact worth keeping."), text("done")]
    client, model = make_client(script)
    expert(client, project_dir, SEARCHING)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="have the Coder ask the Pay expert")
    snap = wait_run(client, cid, run_id, timeout=10)
    assert "proposed" not in [w["status"] for w in snap["web_requests"]]
    assert searched == [{"query": "pay webhook retries", "paid": False}]
    (card,) = snap["questions"]
    assert (card["answer"], card["lead_why"]) == ("Add", "A fact worth keeping.")
    word = {"role": "user", "content": "The Orchestrator, for the user at Full auto, by their rule, answered KOLONİ's "
                                       "card (Pay expert: Add this to the guide?): Add"}
    assert word in model.calls_of["Coder"][1] and word in model.calls_of["Lead"][-1]


def test_under_an_opener_that_does_not_search_it_does_not_either(
    make_client, wait_run, project_dir, monkeypatch
):
    fake_search(monkeypatch, FOUND)
    client, model = make_client({"Lead": [spawn("Pay expert", "what?", "e"), text("done")],
                                 "Pay expert": [text("I do not know.")]})
    lead = next(r for r in client.get("/api/roles").json() if r["name"] == "Lead")
    assert client.patch(f"/api/roles/{lead['id']}", headers=OWN, json={
        "tools": [one for one in lead["tools"] if one != "web_search"]}).status_code == 200
    expert(client, project_dir, SEARCHING)
    cid, run_id = begin(client, project_dir, mode="full_auto", spawn_approval="never",
                        content="ask the Pay expert")
    wait_run(client, cid, run_id)
    assert "web_search" not in offered_to(model, "Pay expert")


def test_not_searching_an_expert_made_without_ask_user_asks_the_user_to_allow_a_search(
    make_client, wait_run, project_dir
):
    # R161 (live): an expert made on the Agents page has no ask_user, so it was told only "never
    # answer from memory" and asked nothing (`questions: []`); it is given one, as any agent asks.
    ask = step(call("ask_user", {"question": "Not in my documents - allow a web search?",
                                 "options": ["Yes", "No"]}, "q1"))
    client, model = make_client({"Lead": [spawn("Pay expert", "when was 3.0 out?", "e"),
                                          text("done")],
                                 "Pay expert": [ask, text("Not in my documents: I do not know.")]})
    role = expert(client, project_dir, EXPERT)
    assert "ask_user" not in role["tools"]
    cid, run_id = begin(client, project_dir, mode="auto_edit", spawn_approval="never",
                        content="ask the Pay expert")
    snap = until(client, cid, lambda s: asked(s) is not None)
    assert asked(snap)["question"].startswith("Not in my documents - allow a web search?")
    assert "ask_user" in offered_to(model, "Pay expert")
    told = next(str(sent[0]["content"]) for sent in model.calls
                if "Your name here is Pay expert." in str(sent[0]["content"]))
    assert "allow a web search?" in told and "never answer it from memory" not in told
    answer(client, asked(snap), "No")
    wait_run(client, cid, run_id)


def test_unwatched_it_searches_only_where_the_trigger_lets_it(
    make_client, wait_run, project_dir, monkeypatch
):
    searched = fake_search(monkeypatch, FOUND)
    docs(project_dir)
    client, _model, pid, cid = setup(make_client, project_dir, {
        "Lead": [spawn("Pay expert", "how long are retries?", "e"), text("done")],
        "Pay expert": [SEARCH, text("I could not search.")],
    })
    expert(client, project_dir, SEARCHING)
    made = trigger(client, pid, cid, permissions={"write": False, "commands": [], "agents": 1})
    snap = wait_run(client, cid, run_now(client, made["id"]), timeout=10)
    refused = next(t for t in snap["tool_calls"] if t["provider_call_id"] == "w1")
    assert refused["status"] == "failed" and NOBODY in refused["result"] and searched == []


# --- kept in the guide ------------------------------------------------------------------------


def test_what_it_was_told_to_keep_is_in_the_guide_at_every_learning(project_dir):
    (project_dir / "api.md").write_text("pay()", encoding="utf-8")
    kept = known("api.md")
    add = knowledge.additions([{"text": "Webhooks are retried for 3 days", "source": FOUND,
                                "label": "official"}])

    async def run(more):
        ask, _asked = asker()
        knowledge.begin(str(project_dir), kept)
        try:
            return await knowledge.learn(str(project_dir), kept, ask, None, "F", added=more)
        finally:
            knowledge.end(str(project_dir), kept)

    asyncio.run(run(add))
    asyncio.run(run([]))  # (learned again, told nothing new)
    guide = knowledge.guide(str(project_dir), kept)
    assert guide.strip().endswith("## Found while answering\n"
                          f"- Webhooks are retried for 3 days · {FOUND} · single source")
    learned_from(project_dir, kept)  # (a learning with nothing to add keeps it too)
    assert "Webhooks are retried for 3 days" in knowledge.guide(str(project_dir), kept)


@pytest.mark.parametrize("sent", [
    "keep it", [{"text": "x", "source": "docs/api.md", "label": "official"}],
    [{"text": " ", "source": FOUND}], [{"text": "x", "source": FOUND}] * 6,
])
def test_what_is_to_be_kept_has_its_words_and_its_address(sent):
    with pytest.raises(ValueError, match="add:"):
        knowledge.additions(sent)


# --- a guide copied to another project ---------------------------------------------------------


def test_a_guide_is_copied_into_another_project_without_the_pages_read(client, project_dir,
                                                                      tmp_path):
    (project_dir / "docs").mkdir()
    (project_dir / "docs" / "api.md").write_text("pay()", encoding="utf-8")
    role = expert(client, project_dir, EXPERT)
    learned_from(project_dir, role["knowledge"])
    other = tmp_path / "other"
    (other / ".koloni" / "knowledge" / "pay" / "pages").mkdir(parents=True)
    (other / ".koloni" / "knowledge" / "pay" / "pages" / "0001.md").write_text("old part")
    (other / ".koloni" / "knowledge" / "pay" / "learned.json").write_text(
        '{"parts": ["0001.md"]}')
    (other / "package.json").write_text('{"dependencies": {"pay": "^3.0"}}')
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    to = client.post("/api/projects", json={"root_path": str(other)}).json()["id"]
    url = f"/api/knowledge/{role['knowledge_id']}/copy"

    # From the app's own page only: it writes into a project.
    assert client.post(url, json={"project_id": pid, "to_project_id": to}).status_code == 403
    same = client.post(url, json={"project_id": pid, "to_project_id": pid}, headers=OWN)
    assert same.status_code == 422
    copied = client.post(url, json={"project_id": pid, "to_project_id": to}, headers=OWN)
    assert copied.status_code == 200, copied.text
    assert copied.json()["guide"] == knowledge.guide(str(project_dir), role["knowledge"])
    # K-bilgi: the knowledge is that project's too, and the expert uses it there in full.
    (mine,) = [r for r in client.get("/api/roles").json() if r["id"] == role["id"]]
    assert [(k["topic"], k["project_id"], k["mode"]) for k in mine["knows"]] == [
        ("Pay", pid, "full"), ("Pay", to, "full")]
    there = other / ".koloni" / "knowledge" / "pay"
    assert sorted(p.relative_to(there).as_posix() for p in there.rglob("*") if p.is_file()) == [
        "guide.md", "learned.json"]
    assert knowledge.learned(str(other), role["knowledge"])["parts"] == []
    # Its version is the project's it is copied into.
    assert knowledge.learned(str(other), role["knowledge"])["version"]["project"] == "3.0"
    # A guide there already is replaced only when the page says so (it asks first).
    again = client.post(url, json={"project_id": pid, "to_project_id": to}, headers=OWN)
    assert again.status_code == 409 and "there is a guide there already" in again.text
    assert client.post(url, json={"project_id": pid, "to_project_id": to, "replace": True},
                       headers=OWN).status_code == 200
    # Not while it learns in either project.
    knowledge.begin(str(other), role["knowledge"])
    try:
        busy = client.post(url, json={"project_id": pid, "to_project_id": to, "replace": True},
                           headers=OWN)
    finally:
        knowledge.end(str(other), role["knowledge"])
    assert busy.status_code == 409 and "it is learning" in busy.text
    # Nothing to copy from a project it has not learned in.
    (tmp_path / "empty").mkdir()
    empty = client.post("/api/projects", json={"root_path": str(tmp_path / "empty")}).json()["id"]
    none = client.post(url, json={"project_id": empty, "to_project_id": pid}, headers=OWN)
    assert none.status_code == 404 and "knowledge not found" in none.text
