"""The small program a CLI starts as its one MCP server.

It carries lines between the CLI (stdio) and KOLONİ's tool server for one session,
which listens on a loopback port and wants a key first. It knows nothing about the
messages it carries. Standard library only: it is started with a bare interpreter.

The port and key come from the JSON file named as its one argument ({"port", "key"}:
`model_session.bridge_file`). The server serves one bridge at a time (B-304).
"""

import json
import os
import socket
import sys
import threading


def where() -> tuple[int, str]:
    with open(sys.argv[1], encoding="utf-8") as config:
        told = json.load(config)
    return int(told["port"]), str(told["key"])


def main() -> int:
    try:
        port, key = where()
        connection = socket.create_connection(("127.0.0.1", port), timeout=10)
    except (OSError, IndexError, KeyError, ValueError) as exc:
        sys.stderr.write(f"koloni bridge: cannot reach the tool server: {exc}\n")
        return 1
    connection.settimeout(None)
    connection.sendall(key.encode("ascii") + b"\n")

    def to_cli() -> None:
        try:
            with connection.makefile("rb") as incoming:
                for line in incoming:
                    sys.stdout.buffer.write(line)
                    sys.stdout.buffer.flush()
        finally:
            os._exit(0)  # KOLONİ closed the session, or the CLI is gone: nothing to carry

    threading.Thread(target=to_cli, daemon=True).start()
    try:
        for line in sys.stdin.buffer:
            connection.sendall(line if line.endswith(b"\n") else line + b"\n")
    except OSError:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
