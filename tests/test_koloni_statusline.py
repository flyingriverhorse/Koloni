"""Slice 87 beside its acceptance set: KOLONİ's status line script sends only the numbers, as
a program does (no Origin), and prints the user's own status line or a short one."""

import http.server
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "koloni_statusline.py"
INPUT = {
    "model": {"id": "claude-opus-5-5", "display_name": "Opus"},
    "workspace": {"current_dir": "C:/work/KOLONİ"},
    "session_id": "a-session",
    "rate_limits": {
        "five_hour": {"used_percentage": 53, "resets_at": 1761300000, "account": "someone"},
        "seven_day": {"used_percentage": 93.4, "resets_at": 1761500000},
        "seven_day_opus": {"used_percentage": 3, "resets_at": 1761500000},
    },
}
# A window that does not say both is left out; the other is still sent.
PARTIAL = {**INPUT, "rate_limits": {
    "five_hour": {"used_percentage": 53, "resets_at": None},
    "seven_day": {"used_percentage": 93.4, "resets_at": 1761500000},
    },
}


@pytest.fixture
def koloni():
    heard = []

    class Koloni(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            heard.append((self.path, dict(self.headers), json.loads(body)))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Koloni)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", heard
    server.shutdown()


def run(*arguments, given=INPUT):
    return subprocess.run([sys.executable, str(SCRIPT), *arguments], input=json.dumps(given).encode(),
                          capture_output=True, timeout=30, check=True).stdout.decode("utf-8")


def test_it_sends_only_the_numbers_with_its_key_and_prints_a_short_line(koloni):
    address, heard = koloni
    assert run("--koloni", address, "--key", "k3y").strip() == "Opus · KOLONİ"
    [(path, headers, body)] = heard
    assert path == "/api/limits/claude-session" and "Origin" not in headers
    assert headers["X-Koloni-Key"] == "k3y"
    assert body == {"five_hour": {"used_percentage": 53, "resets_at": 1761300000},
                    "seven_day": {"used_percentage": 93.4, "resets_at": 1761500000}}
    run("--koloni", address, "--key", "k3y", given=PARTIAL)
    assert heard[1][2] == {"seven_day": {"used_percentage": 93.4, "resets_at": 1761500000}}


def test_it_prints_the_users_own_status_line_with_the_same_input(koloni):
    address, _heard = koloni
    own = f'"{sys.executable}" -c "import sys, json; print(json.load(sys.stdin)[\'session_id\'])"'
    assert run("--koloni", address, "--then", own).strip() == "a-session"


def test_a_status_line_of_the_users_that_hangs_is_ended(koloni):
    address, _heard = koloni
    slow = f'"{sys.executable}" -c "import time; time.sleep(30)"'
    started = time.monotonic()
    assert run("--koloni", address, "--then", slow) == ""
    assert time.monotonic() - started < 10


def test_without_its_limits_or_koloni_it_still_prints(koloni):
    address, heard = koloni
    assert run("--koloni", address, given={"model": {"display_name": "Haiku"}}).strip() == "Haiku"
    assert heard == []
    # Nobody listens there, and an address off this machine is never sent to.
    assert run("--koloni", "http://127.0.0.1:9").strip() == "Opus · KOLONİ"
    assert run("--koloni", "http://example.com").strip() == "Opus · KOLONİ"
