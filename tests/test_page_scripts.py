"""K-39-betik: "Always run in this chat" - a conversation's pages run their scripts without asking.
Remembered on the conversation, off for a new one; turned on only from the app's own page (it lets
scripts run unasked), turned off from anywhere."""

ORIGIN = {"Origin": "http://127.0.0.1:8790"}


def test_always_run_is_kept_on_the_chat_given_from_the_apps_own_page_and_taken_back(make_client):
    client, _model = make_client([])
    cid = client.post("/api/conversations").json()["id"]
    url = f"/api/conversations/{cid}"
    assert client.get(url).json()["conversation"]["page_scripts"] is False
    # an agent's command against the app's address says nothing of where it is from: refused
    assert client.patch(url, json={"page_scripts": True}).status_code == 403
    on = client.patch(url, json={"page_scripts": True}, headers=ORIGIN)
    assert on.status_code == 200 and on.json()["page_scripts"] is True
    assert client.get(url).json()["conversation"]["page_scripts"] is True   # the next page runs
    # another chat asks still
    other = client.post("/api/conversations").json()["id"]
    assert client.get(f"/api/conversations/{other}").json()["conversation"]["page_scripts"] is False
    # asking again is never refused
    off = client.patch(url, json={"page_scripts": False})
    assert off.status_code == 200 and off.json()["page_scripts"] is False


def test_a_chat_moved_to_another_folder_asks_again(make_client, tmp_path):
    client, _model = make_client([])
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    pids = [client.post("/api/projects", json={"root_path": str(p)}, headers=ORIGIN).json()["id"]
            for p in (one, two)]
    cid = client.post(f"/api/projects/{pids[0]}/conversations", headers=ORIGIN).json()["id"]
    url = f"/api/conversations/{cid}"
    assert client.patch(url, json={"page_scripts": True}, headers=ORIGIN).json()["page_scripts"]
    moved = client.patch(url, json={"project_id": pids[1]}, headers=ORIGIN)
    assert moved.status_code == 200, moved.text
    assert moved.json()["page_scripts"] is False
