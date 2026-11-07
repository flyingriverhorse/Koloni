"""KOLONİ's status line for Claude Code: what is left of your plan, sent to KOLONİ as it changes.

Claude Code runs a status line command with what it knows of the session as JSON on stdin; on
Pro and Max that holds `rate_limits` (how much of the 5-hour and weekly windows is used, and
when each resets). This sends only those numbers to KOLONİ on this machine, with the key of
KOLONİ's setup (`--key`, so that nothing else on the machine can say them), then prints your
own status line (`--then "<its command>"`, given the same input) or a short one of its own.
It never fails or holds up the status line: KOLONİ not running is no error. Nothing else of
the input - no account, email or token - is read, sent or printed. Standard library only.
The command to put in Claude Code's settings is on KOLONİ's Models page (Claude Code, Limits).
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

WINDOWS = ("five_hour", "seven_day")
KEPT = ("used_percentage", "resets_at")
SECONDS = 0.25  # the most the status line waits for KOLONİ
THEIRS = 2.0  # the most it waits for your own status line (`--then`)
HERE = ("127.0.0.1", "localhost", "::1")


def numbers(given: object) -> dict:
    """Only what KOLONİ keeps of the input: each window's share used and its reset; a
    window that does not say both is left out."""
    limits = given.get("rate_limits") if isinstance(given, dict) else None
    if not isinstance(limits, dict):
        return {}
    return {
        name: {key: part[key] for key in KEPT}
        for name in WINDOWS if isinstance(part := limits.get(name), dict)
        and all(part.get(key) is not None for key in KEPT)
    }


def send(koloni: str, key: str, limits: dict) -> None:
    try:
        # Only to this machine, and never through a proxy the environment names.
        address = urlsplit(koloni)
        if address.scheme != "http" or address.hostname not in HERE:
            return
        request = urllib.request.Request(
            koloni.rstrip("/") + "/api/limits/claude-session", data=json.dumps(limits).encode(),
            headers={"Content-Type": "application/json", "X-Koloni-Key": key}, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        opener.open(request, timeout=SECONDS).close()
    except Exception:
        pass  # KOLONİ not running, or saying no: the status line goes on all the same


def plain(given: object) -> str:
    """The model's name and the folder's, where the input says them."""
    given = given if isinstance(given, dict) else {}
    model = given.get("model") if isinstance(given.get("model"), dict) else {}
    workspace = given.get("workspace") if isinstance(given.get("workspace"), dict) else {}
    folder = workspace.get("current_dir") or given.get("cwd")
    parts = [model.get("display_name"), Path(folder).name if isinstance(folder, str) else None]
    return " · ".join(part for part in parts if isinstance(part, str) and part)


def theirs(command: str, raw: bytes) -> None:
    """Run the user's own status line with the same input; past `THEIRS` it is ended, with
    whatever it started (which would hold the status line's output open)."""
    # shortcut: run by this system's own shell (cmd on Windows), which may not be the one
    # Claude Code runs status lines with; take the shell from Claude Code if that matters.
    own = subprocess.Popen(command, shell=True, stdin=subprocess.PIPE, start_new_session=True)
    try:
        own.communicate(raw, timeout=THEIRS)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(own.pid)], capture_output=True)
        else:
            os.killpg(own.pid, signal.SIGKILL)
        own.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description="KOLONİ's status line for Claude Code")
    parser.add_argument("--koloni", default="http://127.0.0.1:8790", help="KOLONİ's address")
    parser.add_argument("--key", default="", help="the key of KOLONİ's status line setup")
    parser.add_argument("--then", help="your own status line command, run with the same input")
    args = parser.parse_args()
    raw = sys.stdin.buffer.read()
    try:
        given = json.loads(raw)
    except (ValueError, RecursionError):
        given = None
    limits = numbers(given)
    sending = threading.Thread(target=send, args=(args.koloni, args.key, limits), daemon=True)
    if limits:
        sending.start()
    if args.then:
        theirs(args.then, raw)
    else:
        # As bytes: a folder's name cannot always be written in a pipe's own code page.
        sys.stdout.buffer.write((plain(given) + "\n").encode("utf-8"))
        sys.stdout.flush()
    if limits:
        sending.join(SECONDS)


if __name__ == "__main__":
    main()
