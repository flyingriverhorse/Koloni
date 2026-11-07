"""Slice 39's acceptance set, the backend's part: what agents write to be seen, shown beside
the chat. Written before the code.

A page, a drawing or a note an agent writes in the conversation is listed to be seen - while its
change still waits, too, and as it will be. An agent can put any file of the project before the
user with `show`, a picture among them; not one outside it. A page is served to the app's own
frame only, under a policy that lets its script run but lets it reach nothing: neither the app
nor the outside. What a page asks for beside itself is served from where it lies, and nothing
outside the project, by any name. A rejected change is no longer listed.

Each view carries the `url` its frame loads; what the page names beside itself is asked for
relative to that url, as a browser would.
"""

import importlib.util
import json
import os
from urllib.parse import urljoin

import pytest

if importlib.util.find_spec("app.views") is None:
    pytest.skip("slice 39 is not built yet", allow_module_level=True)  # written before the code

from tests.test_agent_writes import wait_status, write  # noqa: E402
from tests.test_chat_flow import start, start_in_mode, text  # noqa: E402
from tests.test_spawn import call, step  # noqa: E402

PAGE = "<!doctype html><title>t</title><script>document.title = 'ran'</script><p>hi</p>"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)
# Where a page's own script, style, picture and font may come from: itself, or beside it.
OWN = {"'self'", "'unsafe-inline'", "'unsafe-eval'", "data:", "blob:"}


def views(client, cid):
    answer = client.get(f"/api/conversations/{cid}/views")
    assert answer.status_code == 200, answer.text
    return answer.json()


def content(client, view):
    assert view["url"].startswith("/api/"), view["url"]   # served by the app itself
    return client.get(view["url"])


def show(path, note=None, id="v1"):
    return step(call("show", {"path": path, **({"note": note} if note else {})}, id))


def policy(answer):
    return " ".join(answer.headers.get_list("content-security-policy")).lower()


def directives(answer):
    """The answer's policies as {directive: every source any of them names}. A second
    policy (say, one added on the way out) shows up here rather than hiding."""
    found: dict[str, set[str]] = {}
    for one in answer.headers.get_list("content-security-policy"):
        for part in one.lower().split(";"):
            words = part.split()
            if words:
                found.setdefault(words[0], set()).update(words[1:])
    return found


def link(outside, inside):
    try:
        os.link(outside, inside)
    except OSError as exc:  # a file system without them
        pytest.skip(f"no hard links here: {exc}")


# --- what is listed ----------------------------------------------------------------------------


def test_a_page_an_agent_writes_is_listed_while_its_change_still_waits(make_client, project_dir):
    client, _model = make_client([write("page.html", PAGE), text("Here it is.")])
    cid, _run_id = start(client, project_dir)                    # Ask: the change waits
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    (view,) = views(client, cid)
    assert view["path"] == "page.html" and view["kind"] == "html"
    assert view["status"] == "proposed" and view["agent_id"] == change["agent_id"]
    # What is shown is the page as it will be: it is not in the project yet.
    assert not (project_dir / "page.html").exists()
    answer = content(client, view)
    assert answer.status_code == 200 and answer.text == PAGE
    assert answer.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("path,kind", [("d.svg", "svg"), ("notes.md", "md"), ("p.htm", "html")])
def test_drawings_and_notes_are_listed_too(make_client, project_dir, path, kind):
    client, _model = make_client([write(path, "<svg/>" if kind == "svg" else "# hi\n"), text("ok")])
    cid, _run_id = start(client, project_dir)
    wait_status(client, cid, "waiting_approval")
    assert [(v["path"], v["kind"]) for v in views(client, cid)] == [(path, kind)]


def test_a_file_of_another_kind_is_not_listed(make_client, project_dir):
    client, _model = make_client([write("tool.py", "print(1)\n"), text("ok")])
    cid, _run_id = start(client, project_dir)
    wait_status(client, cid, "waiting_approval")
    assert views(client, cid) == []


def test_a_rejected_change_is_no_longer_listed(make_client, wait_run, project_dir):
    client, _model = make_client([write("page.html", PAGE), text("ok")])
    cid, run_id = start(client, project_dir)
    change = wait_status(client, cid, "waiting_approval")["file_changes"][0]
    assert client.post(f"/api/file-changes/{change['id']}/reject").json()["status"] == "rejected"
    wait_run(client, cid, run_id)
    assert views(client, cid) == []


def test_the_page_applied_reads_as_applied_and_its_newest_text_is_shown(
    make_client, wait_run, project_dir
):
    client, _model = make_client([
        write("page.html", "<p>one</p>", id="w1"), write("page.html", "<p>two</p>", id="w2"),
        text("ok")])
    cid, run_id = start_in_mode(client, project_dir, "auto_edit")   # changes are applied
    wait_run(client, cid, run_id)
    (view,) = views(client, cid)                                 # one line for one file
    assert view["status"] == "applied"
    assert content(client, view).text == "<p>two</p>"


# --- show --------------------------------------------------------------------------------------


def test_an_agent_shows_a_picture_of_the_project(make_client, wait_run, project_dir):
    (project_dir / "chart.png").write_bytes(PNG)
    client, _model = make_client([show("chart.png", "the chart"), text("Look at the chart.")])
    cid, run_id = start(client, project_dir)
    snap = wait_run(client, cid, run_id)
    (tool,) = snap["tool_calls"]
    assert tool["status"] == "succeeded", tool["result"]
    (view,) = views(client, cid)
    assert view["path"] == "chart.png" and view["kind"] == "image" and view["note"] == "the chart"
    answer = content(client, view)
    assert answer.status_code == 200 and answer.content == PNG
    assert answer.headers["content-type"] == "image/png"


@pytest.mark.parametrize("where", ["above", "absolute", "unc", "missing", "other kind", "linked"])
def test_show_puts_nothing_outside_the_project_missing_or_of_another_kind_before_the_user(
    make_client, wait_run, project_dir, tmp_path, where
):
    outside = tmp_path / "outside.png"           # a real picture, of a kind that is shown
    outside.write_bytes(PNG)
    if where == "linked":                        # inside by name, outside in fact
        link(outside, project_dir / "linked.png")
    path = {
        "above": "../outside.png",
        "absolute": str(outside),
        "unc": "\\\\127.0.0.1\\" + str(outside).replace(":", "$", 1),
        "missing": "missing.png",
        "other kind": "hello.py",
        "linked": "linked.png",
    }[where]
    client, _model = make_client([show(path), text("ok")])
    cid, run_id = start(client, project_dir)
    snap = wait_run(client, cid, run_id)
    (tool,) = snap["tool_calls"]
    assert tool["status"] == "failed"
    assert views(client, cid) == []


def test_show_asks_nobody(make_client, wait_run, project_dir):
    (project_dir / "chart.png").write_bytes(PNG)
    client, _model = make_client([show("chart.png"), text("ok")])
    cid, run_id = start(client, project_dir)                     # Ask: yet nothing waits
    assert wait_run(client, cid, run_id)["runs"][0]["status"] == "completed"


def test_a_file_too_large_is_listed_but_not_served(make_client, wait_run, project_dir):
    (project_dir / "big.png").write_bytes(PNG + b"\0" * (5 * 1024 * 1024))
    client, _model = make_client([show("big.png"), text("ok")])
    cid, run_id = start(client, project_dir)
    wait_run(client, cid, run_id)
    (view,) = views(client, cid)
    assert content(client, view).status_code == 413


def test_a_shown_file_changed_on_disk_is_served_as_it_now_is(make_client, wait_run, project_dir):
    (project_dir / "out.html").write_text("<p>one</p>")
    client, _model = make_client([show("out.html"), text("ok")])
    cid, run_id = start(client, project_dir)
    wait_run(client, cid, run_id)
    (view,) = views(client, cid)
    (project_dir / "out.html").write_text("<p>two</p>")
    assert content(client, view).text == "<p>two</p>"
    assert views(client, cid)[0]["sha"] != view["sha"]           # the panel can tell it changed


# --- the sandbox -------------------------------------------------------------------------------


def test_a_page_runs_its_script_but_reaches_neither_the_app_nor_the_outside(make_client, project_dir):
    client, _model = make_client([write("page.html", PAGE), text("ok")])
    cid, _run_id = start(client, project_dir)
    wait_status(client, cid, "waiting_approval")
    said = directives(content(client, views(client, cid)[0]))
    # Its own sandbox, even opened alone: script, and nothing else - no origin of its own,
    # no navigating the app away, no windows, no forms.
    assert said.get("sandbox") == {"allow-scripts"}, said
    # Nothing is fetched unless named here, and nothing at all is reached by script or form.
    assert said.get("default-src") == {"'none'"}, said
    for rule in ("connect-src", "form-action", "frame-src", "base-uri"):
        assert said.get(rule) == {"'none'"}, (rule, said)
    # Its script runs, and what it draws with comes from itself or from beside it.
    assert said.get("script-src") and "'none'" not in said["script-src"], said
    for rule in ("script-src", "style-src", "img-src", "font-src"):
        assert said.get(rule, set()) <= OWN, (rule, said)


def test_a_page_is_framed_by_the_app_alone_and_the_rest_by_nobody(make_client, project_dir):
    client, _model = make_client([write("page.html", PAGE), text("ok")])
    cid, _run_id = start(client, project_dir)
    wait_status(client, cid, "waiting_approval")
    page = content(client, views(client, cid)[0])
    assert directives(page).get("frame-ancestors") == {"'self'"}, policy(page)
    assert page.headers.get("x-frame-options", "SAMEORIGIN").upper() == "SAMEORIGIN"
    # Every other answer is still framed by nobody (slice 36).
    other = client.get(f"/api/conversations/{cid}/views")
    assert "frame-ancestors 'none'" in policy(other)


def site(project_dir):
    (project_dir / "site").mkdir()
    (project_dir / "site" / "index.html").write_text("<link rel=stylesheet href=style.css>")
    (project_dir / "site" / "style.css").write_text("p{color:red}")


def test_what_a_page_names_beside_itself_is_served_from_where_it_lies(
    make_client, wait_run, project_dir
):
    site(project_dir)
    client, _model = make_client([show("site/index.html"), text("ok")])
    cid, run_id = start(client, project_dir)
    wait_run(client, cid, run_id)
    (view,) = views(client, cid)
    beside = client.get(urljoin(view["url"], "style.css"))      # as the browser asks for it
    assert beside.status_code == 200 and beside.text == "p{color:red}"
    assert beside.headers["content-type"].startswith("text/css")


@pytest.mark.parametrize("asked", ["..%2F..%2Fsecret.css", "%2E%2E%2F%2E%2E%2Fsecret.css",
                                   "..%5C..%5Csecret.css", "linked.css", "ABSOLUTE"])
def test_nothing_outside_the_project_is_served_beside_a_page_by_any_name(
    make_client, wait_run, project_dir, tmp_path, asked
):
    site(project_dir)
    secret = tmp_path / "secret.css"             # outside the project, of a kind that is served
    secret.write_text("secret")
    if asked == "linked.css":
        link(secret, project_dir / "site" / "linked.css")
    client, _model = make_client([show("site/index.html"), text("ok")])
    cid, run_id = start(client, project_dir)
    wait_run(client, cid, run_id)
    (view,) = views(client, cid)
    if asked == "ABSOLUTE":
        asked = str(secret).replace("\\", "%2F").replace(":", "%3A")
    answer = client.get(urljoin(view["url"], asked))
    assert answer.status_code in (400, 404), (asked, answer.status_code)
    assert "secret" not in answer.text


def test_views_of_one_conversation_are_not_served_under_another(make_client, project_dir):
    client, _model = make_client([write("page.html", PAGE), text("ok")])
    cid, _run_id = start(client, project_dir)
    wait_status(client, cid, "waiting_approval")
    (view,) = views(client, cid)
    pid = client.get(f"/api/conversations/{cid}").json()["conversation"]["project_id"]
    other = client.post(f"/api/projects/{pid}/conversations").json()["id"]
    assert cid in view["url"]
    assert client.get(view["url"].replace(cid, other)).status_code == 404


def test_the_show_tool_is_offered_to_the_agent(make_client, project_dir, wait_run):
    client, model = make_client([text("ok")])
    cid, run_id = start(client, project_dir)
    wait_run(client, cid, run_id)
    offered = [tool["function"]["name"] for tool in model.tool_args[0]]
    assert "show" in offered, json.dumps(offered)
