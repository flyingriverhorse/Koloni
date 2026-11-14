"""An answer sent packed although it was asked for as it is (`app.web._send`): what comes back
of it. Against a server of the test's, on loopback - nothing leaves this machine."""

import gzip
import threading
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer

from app import web

BODIES = {
    "/gzip": ("gzip", gzip.compress(b"hello " * 10)),
    "/deflate": ("deflate", zlib.compress(b"hello " * 10)),
    "/GZIP": ("GZIP", gzip.compress(b"upper")),
    "/broken": ("gzip", b"not packed at all"),
    "/br": ("br", b"left as it came"),
    "/bomb": ("gzip", gzip.compress(b"a" * (web.MAX_BYTES + 100_000))),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        encoding, body = BODIES[self.path]
        self.send_response(200)
        self.send_header("Content-Encoding", encoding)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_a_packed_answer_is_unpacked_no_further_than_is_read():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://name.invalid:{server.server_address[1]}"

        def body(path: str) -> bytes:
            answer = web._send("GET", url + path, {}, None, "127.0.0.1")
            assert answer.status == 200 and not answer.cut
            return answer.body

        assert body("/gzip") == b"hello " * 10
        assert body("/deflate") == b"hello " * 10
        assert body("/GZIP") == b"upper"
        # one that is not what it says, or packed another way, comes back as it was sent
        assert body("/broken") == b"not packed at all"
        assert body("/br") == b"left as it came"
        # a small answer does not become a huge one
        assert body("/bomb") == b"a" * (web.MAX_BYTES + 1)
    finally:
        server.shutdown()
        server.server_close()
