"""K-yargıç, slice 1: at Full auto, in a turn the user watches, a command that deletes or sends
something off this machine is first checked against what the user themself wrote - their
preferences, this project's rules as saved, their own messages in the chat - and runs without a
card only on a line of theirs that names it; anything else is today's card. Off by default."""

from app import koloni
from tests.keyed import OWN


def test_a_project_asks_as_before_until_the_user_turns_the_check_on(client, project_dir):
    pid = client.post("/api/projects", json={"root_path": str(project_dir)}).json()["id"]
    assert client.get(f"/api/projects/{pid}").json()["full_auto_check"] == "ask"
    assert client.patch(f"/api/projects/{pid}", json={"full_auto_check": "judge"}).status_code == 403
    assert client.patch(f"/api/projects/{pid}", json={"full_auto_check": "judge"},
                        headers=OWN).json()["full_auto_check"] == "judge"
    assert "full_auto_check" not in koloni.SETTINGS
