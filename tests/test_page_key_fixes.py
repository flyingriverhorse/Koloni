"""Slice 94's review fixes: what is served outside /api, where no key is asked, and the
window's link as `run()` prints it."""

import json
import logging

from fastapi.testclient import TestClient

import app.main
from app.config import load_settings
from app.main import create_app


def test_the_api_says_nothing_of_itself_where_no_key_is_asked(settings_env):
    made = create_app(load_settings(settings_env))
    with TestClient(made, base_url="http://127.0.0.1:8790") as client:
        for address in ("/docs", "/redoc", "/openapi.json"):
            # (404, or the page itself where a build is there to serve it.)
            said = client.get(address).text.lower()
            assert "swagger" not in said and "redoc" not in said and "/api/health" not in said
    # What the page is typed against is still made from the app (`scripts/export_openapi.py`).
    assert "/api/health" in json.dumps(made.openapi())


def test_run_shows_the_link_with_the_apps_own_key(monkeypatch, settings_env, capsys, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error")  # (uvicorn's own level, as it runs)
    for name, value in {**settings_env, "KOLONI_PAGE_KEY": "k" * 40}.items():
        monkeypatch.setenv(name, value)

    def serve(made, **_):
        assert made.state.page_key == "k" * 40
        logging.getLogger("uvicorn.error").info(
            "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)", "http", "127.0.0.1", 8790)

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", serve)
    window = logging.getLogger("uvicorn.error")
    before = list(window.filters)
    try:
        app.main.run()
    finally:
        window.filters[:] = before
    assert f"http://127.0.0.1:8790/#key={'k' * 40}" in capsys.readouterr().out
