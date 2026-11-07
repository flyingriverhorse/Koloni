from fastapi.testclient import TestClient  # (not tests.keyed's: the guide needs no page key)

from app.config import load_settings
from app.main import create_app
from tests.fakes import ScriptedModel


def client_for(root):
    settings = load_settings({"KOLONI_RUNTIME_ROOT": str(root / "rt")}, repo_root=root)
    return TestClient(create_app(settings, model=ScriptedModel([])), base_url="http://127.0.0.1:8790")


def test_the_built_guide_is_served_without_the_page_key_and_nothing_beside_it(tmp_path):
    site = tmp_path / "runtime" / "site"
    (site / "settings").mkdir(parents=True)
    (site / "index.html").write_text("<title>guide home</title>", encoding="utf-8")
    (site / "settings" / "index.html").write_text("<h2 id='app'>App</h2>", encoding="utf-8")
    (tmp_path / "runtime" / "secret.txt").write_text("outside the site", encoding="utf-8")
    with client_for(tmp_path) as client:
        assert client.get("/api/projects").status_code == 401  # (no key, as the test means)
        assert "guide home" in client.get("/guide/").text
        assert client.get("/guide", follow_redirects=False).headers["location"] == "/guide/"
        assert "id='app'" in client.get("/guide/settings/").text
        for escape in ("/guide/%2e%2e/secret.txt", "/guide/..%2Fsecret.txt", "/guide/..%5csecret.txt",
                       "/guide/C:%5CWindows%5Cwin.ini", "/guide/%5C%5Cserver%5Cshare"):
            answer = client.get(escape)
            assert answer.status_code == 404, escape
            assert "outside the site" not in answer.text
        # Names Windows will not look up: not found, never a 500.
        for odd in ("a%3Fb", "a*b", "a%3Cb", "a%7Cb", "a%22b", "a" * 300):
            assert client.get(f"/guide/{odd}").status_code == 404, odd


def test_every_answer_of_the_guide_keeps_cdn_scripts_out(tmp_path):
    site = tmp_path / "runtime" / "site"
    site.mkdir(parents=True)
    (site / "index.html").write_text("guide home", encoding="utf-8")
    with client_for(tmp_path) as client:
        for path in ("/guide/", "/guide/nope", "/guide/a%3Fb"):
            headers = client.get(path).headers
            assert headers["x-content-type-options"] == "nosniff", path
            policy = headers.get_list("content-security-policy")
            # One policy: NoFrame adds none of its own beside it.
            assert len(policy) == 1 and "script-src 'self' 'unsafe-inline';" in policy[0], path
            assert "frame-ancestors 'none'" in policy[0] and "unpkg" not in policy[0]


def test_without_a_build_the_guide_says_how_to_make_one(tmp_path):
    (tmp_path / "zensical.toml").write_text(
        '[project]\nsite_url = "https://example.github.io/koloni/"\n', encoding="utf-8")
    with client_for(tmp_path) as client:
        answer = client.get("/guide/settings/")
        assert answer.status_code == 404
        assert "The guide is not built yet" in answer.text
        assert "zensical build" in answer.text
        assert 'href="https://example.github.io/koloni/"' in answer.text
        assert "frame-ancestors 'none'" in answer.headers["content-security-policy"]
        # Built while KOLONİ runs: served at once.
        (tmp_path / "runtime" / "site").mkdir(parents=True)
        (tmp_path / "runtime" / "site" / "index.html").write_text("guide home", encoding="utf-8")
        assert client.get("/guide/").text == "guide home"
