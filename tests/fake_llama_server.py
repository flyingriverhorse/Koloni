"""A stand-in for llama-server (slice 64): it serves `/v1/models` and `/props` on its
`--port`, as the model `-m` names and with the window `-c` gives - with `--api-key`, only to
a request that carries it - and prints a few lines, with a key in them, which the window it
is shown in hides. Unknown arguments are taken as llama-server takes them, without a word."""

import http.server
import json
import pathlib
import sys

args = sys.argv[1:]


def value(*names: str, default: str = "") -> str:
    """The last value given, as `--name value` or `--name=value`."""
    found = default
    for at, arg in enumerate(args):
        for name in names:
            if arg == name and at + 1 < len(args):
                found = args[at + 1]
            elif arg.startswith(f"{name}="):
                found = arg[len(name) + 1:]
    return found


port = int(value("--port", default="8080"))
model = pathlib.PurePath(value("-m", "--model", default="none.gguf").replace("\\", "/")).name
n_ctx = int(value("-c", "--ctx-size", default="4096"))
key = value("--api-key")


class Server(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if key and self.headers.get("Authorization") != f"Bearer {key}":
            self.send_response(401)
            self.end_headers()
            return
        if self.path == "/v1/models":
            body = {"object": "list", "data": [{"id": model, "object": "model"}]}
        elif self.path == "/props":
            body = {"default_generation_settings": {"n_ctx": n_ctx}}
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Server)
print(f"fake llama-server: loading model {model}", flush=True)
print("fake llama-server: key sk-fake0123456789abcdefghijkl", flush=True)
if key:
    print(f"fake llama-server: api key: {key}", flush=True)
print(f"main: server is listening on http://127.0.0.1:{port} - n_ctx {n_ctx}", flush=True)
server.serve_forever()
