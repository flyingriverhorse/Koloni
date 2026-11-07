from app.config import load_settings
from app.main import create_app
from tests.fakes import ScriptedModel
from tests.keyed import TestClient


def test_serves_built_frontend_when_present(tmp_path):
    dist = tmp_path / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>KOLONİ</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("1", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside dist", encoding="utf-8")
    settings = load_settings({"KOLONI_RUNTIME_ROOT": str(tmp_path / "rt")}, repo_root=tmp_path)
    with TestClient(
        create_app(settings, model=ScriptedModel([])), base_url="http://127.0.0.1:8790"
    ) as client:
        assert "KOLONİ" in client.get("/").text
        assert client.get("/assets/app.js").text == "1"
        assert client.get("/favicon.svg").text == "<svg/>"
        assert "KOLONİ" in client.get("/some/client/route").text
        assert client.get("/api/nope").status_code == 404
        assert client.get("/api/projects").status_code == 200
        escaped = client.get("/..%2F..%2Fsecret.txt")
        assert "outside dist" not in escaped.text


def test_without_a_build_the_api_still_works(tmp_path):
    settings = load_settings({"KOLONI_RUNTIME_ROOT": str(tmp_path / "rt")}, repo_root=tmp_path)
    with TestClient(
        create_app(settings, model=ScriptedModel([])), base_url="http://127.0.0.1:8790"
    ) as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/projects").status_code == 200


def test_the_page_is_served_as_script_whatever_the_registry_says(tmp_path):
    """Python reads .js's type from Windows' registry, which some installers set to text/plain:
    the browser refused the page's modules and showed nothing."""
    import mimetypes

    dist = tmp_path / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("1", encoding="utf-8")
    (dist / "assets" / "app.css").write_text("a{}", encoding="utf-8")
    mimetypes.add_type("text/plain", ".js")  # (as such a registry says)
    mimetypes.add_type("text/plain", ".css")
    settings = load_settings({"KOLONI_RUNTIME_ROOT": str(tmp_path / "rt")}, repo_root=tmp_path)
    with TestClient(
        create_app(settings, model=ScriptedModel([])), base_url="http://127.0.0.1:8790"
    ) as client:
        assert client.get("/assets/app.js").headers["content-type"].startswith("text/javascript")
        assert client.get("/assets/app.css").headers["content-type"].startswith("text/css")
