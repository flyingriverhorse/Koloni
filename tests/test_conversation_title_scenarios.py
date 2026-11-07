"""Slice 67's acceptance set (backend part): a conversation's title reads whole. Written before the code.

The user, 21 Oct (on the Conversations page): titles like "calc.html adinda basit bir hesap makinesi
sayfasi yaz (HTML+" are cut mid-word. A title made from the first message is its first line, cut at a
word's end (never inside a word or after an opening bracket) and ended with "…" when cut; at most
60 characters with the "…". A short message is its own title, unchanged.
"""

import pytest

from app.api import conversations

if not hasattr(conversations, "title_from"):
    pytest.skip("slice 67 is not built yet", allow_module_level=True)  # written before the code

from app.api.conversations import title_from  # noqa: E402


def test_a_short_message_is_its_own_title():
    assert title_from("make a calculator") == "make a calculator"


def test_a_long_message_is_cut_at_a_words_end_with_an_ellipsis():
    said = "calc.html adinda basit bir hesap makinesi sayfasi yaz (HTML+CSS+JS tek dosya)"
    title = title_from(said)
    assert len(title) <= 60 and title.endswith("…")
    assert title == "calc.html adinda basit bir hesap makinesi sayfasi yaz…"


def test_only_the_first_line_and_plain_spaces():
    assert title_from("fix the login\n\nthe button does nothing   when   clicked") == "fix the login"
    assert title_from("  many    spaces  here ") == "many spaces here"


def test_a_single_long_word_is_cut_rather_than_left_empty():
    title = title_from("x" * 200)
    assert title == "x" * 59 + "…"


def test_the_first_message_names_the_conversation(client, project_dir):
    origin = {"Origin": "http://127.0.0.1:8790"}
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}, headers=origin).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations", headers=origin).json()["id"]
    client.post(f"/api/conversations/{cid}/messages", headers=origin, json={
        "content": "calc.html adinda basit bir hesap makinesi sayfasi yaz (HTML+CSS+JS tek dosya)"})
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["title"] == (
        "calc.html adinda basit bir hesap makinesi sayfasi yaz…")


def test_a_title_set_before_the_first_message_stays(client, project_dir):
    # R194 (live): a title given by PATCH was overwritten by the first message's.
    origin = {"Origin": "http://127.0.0.1:8790"}
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}, headers=origin).json()["id"]
    cid = client.post(f"/api/projects/{pid}/conversations", headers=origin).json()["id"]
    assert client.patch(f"/api/conversations/{cid}", headers=origin,
                        json={"title": "Calculator"}).status_code == 200
    client.post(f"/api/conversations/{cid}/messages", headers=origin, json={"content": "make it"})
    assert client.get(f"/api/conversations/{cid}").json()["conversation"]["title"] == "Calculator"
