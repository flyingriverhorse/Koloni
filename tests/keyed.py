"""The test client every test uses: it carries the app's page key, as KOLONİ's page does
(slice 94). Only the acceptance set of the key builds one without it."""

import re

from fastapi import testclient

CHAT = re.compile(r"^(?:https?://[^/]+)?/api/conversations/([0-9a-f]+)$")
# What a chat of a project does not set itself (`app.api.conversations.PROJECT_WIDE`).
PROJECT_WIDE = {"spawn_approval", "spawn_max_depth", "spawn_max_agents", "spawn_max_parallel",
                "discussion_budget", "when_away", "away_minutes", "room_posts", "room_tokens",
                "room_minutes", "room_min_tokens", "lead_work", "lead_hands_code"}


# The approvals and their kin the app's own page alone may send (security review 0.1.0, 9).
OWN_ONLY = {
    "POST": re.compile(r"(?:https?://[^/]+)?/api/(?:(?:commands|agents|tool-calls|file-changes)"
                       r"/[^/]+/(?:approve|reject|revert)|(?:discussions|rooms)/[^/]+/posts"
                       r"|providers/[^/]+/default|roles|roles/[^/]+/reset|conversations/[^/]+/attachments/project)"),
    "DELETE": re.compile(r"(?:https?://[^/]+)?/api/(?:providers|roles|allowed-commands)/[^/]+"),
}
OWN = {"Origin": "http://127.0.0.1:8790"}
# What a test of the refusal sends: no origin at all - not even the page's (`request`).
NO_ORIGIN = {"Origin": None}


class TestClient(testclient.TestClient):
    def __init__(self, app, *args, headers=None, **kwargs):
        # (A small app of a test's own, not KOLONİ's, has no key to carry.)
        key = {"X-KOLONI-Key": app.state.page_key} if hasattr(app.state, "page_key") else {}
        super().__init__(app, *args, headers={**key, **(headers or {})}, **kwargs)

    def request(self, method, url, *args, headers=None, **kwargs):
        """What only the app's own page may send (`OWN_ONLY`) says it is from there, where the
        test says nothing of where it is from: as the page does.
        shortcut: so the tests of before review 9 send these as they did; a test of the refusal
        itself sends another origin, or none (`NO_ORIGIN`)."""
        if any(name.lower() == "origin" for name in headers or {}):
            headers = {name: value for name, value in headers.items() if value is not None}
        elif (own := OWN_ONLY.get(method.upper())) and own.fullmatch(str(url).partition("?")[0]):
            headers = {**(headers or {}), **OWN}
        return super().request(method, url, *args, headers=headers, **kwargs)

    def patch(self, url, *args, json=None, **kwargs):
        """A chat's PATCH, its sub-agent settings sent to its project's PATCH, as Settings ›
        Project does (tek-ev: a project's chat is refused them, 422).
        shortcut: so the tests of before tek-ev set a chat's turn up as they did; a test of
        that refusal itself sends `request("PATCH", ...)`. Move them over if this misleads."""
        chat = CHAT.match(str(url))
        moved = {key: json[key] for key in PROJECT_WIDE & set(json)} if (
            chat and isinstance(json, dict)) else {}
        pid = moved and self.get(f"/api/conversations/{chat[1]}").json()["conversation"][
            "project_id"]
        if pid:
            if "lead_hands_code" in moved:
                moved["lead_work"] = "delegates" if moved.pop("lead_hands_code") else "itself"
            done = super().patch(f"/api/projects/{pid}", json=moved,
                                 headers=kwargs.get("headers"))
            if done.status_code != 200:
                return done
            json = {key: value for key, value in json.items() if key not in PROJECT_WIDE}
        return super().patch(url, *args, json=json, **kwargs)
