import pytest

import app.main as main
from app.config import load_settings


def test_defaults(tmp_path):
    s = load_settings({"KOLONI_RUNTIME_ROOT": str(tmp_path)})
    assert s.db_path == tmp_path / "data" / "koloni.db"
    assert s.model_base_url == "http://127.0.0.1:8080/v1"
    assert s.model_id is None and s.model_api_key is None
    assert s.max_steps == 25
    assert s.host == "127.0.0.1"  # this machine only; 0.0.0.0 is the Docker image's alone
    assert "http://127.0.0.1:8790" in s.allowed_origins
    # Vite's dev page (5173) only in development: an agent's own Vite page can be on it too
    assert not any(":5173" in origin for origin in s.allowed_origins)
    dev = load_settings({"KOLONI_RUNTIME_ROOT": str(tmp_path), "KOLONI_DEV": "1"})
    assert {"http://127.0.0.1:5173", "http://localhost:5173"} <= set(dev.allowed_origins)


def test_overrides(tmp_path):
    s = load_settings({
        "KOLONI_RUNTIME_ROOT": str(tmp_path),
        "KOLONI_MODEL_BASE_URL": "http://127.0.0.1:9999/v1/",
        "KOLONI_MODEL_ID": "m",
        "KOLONI_HOST": "0.0.0.0",
    })
    assert s.model_base_url == "http://127.0.0.1:9999/v1"
    assert s.model_id == "m"
    assert s.host == "0.0.0.0"


def test_port_override_is_an_allowed_origin(tmp_path):
    s = load_settings({"KOLONI_RUNTIME_ROOT": str(tmp_path), "KOLONI_PORT": "8791"})
    assert s.port == 8791
    assert "http://127.0.0.1:8791" in s.allowed_origins
    assert "http://localhost:8791" in s.allowed_origins
    assert load_settings({"KOLONI_RUNTIME_ROOT": str(tmp_path)}).port == 8790


def test_only_this_machine_unless_in_the_image():
    for host in ("127.0.0.1", "::1", "localhost"):
        assert main.bind_allowed(host, {})
    for host in ("0.0.0.0", "::", "192.168.1.5"):
        assert not main.bind_allowed(host, {}), host
        assert main.bind_allowed(host, {"KOLONI_IN_CONTAINER": "1"}), host


def test_run_refuses_an_open_address_before_it_starts(monkeypatch, tmp_path):
    monkeypatch.setenv("KOLONI_HOST", "0.0.0.0")
    monkeypatch.setenv("KOLONI_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.delenv("KOLONI_IN_CONTAINER", raising=False)
    monkeypatch.setattr(main, "not_dumpable", lambda: None)
    monkeypatch.setattr(main, "create_app", lambda _: pytest.fail("started"))
    with pytest.raises(SystemExit, match="no TLS"):
        main.run()
    assert not (tmp_path / "logs").exists()  # refused before anything was set up
