"""k-bakis-yeri B1: the whole kept work a Fix it turn's look reads (`merge.kept_work`) is built as
Take in shows it: what Take in leaves out is not in it, and a secret file, one whose secret was
given on a card, one holding a secret of the turn's, one not text are named - never read into
the diff a model is sent. In a child process (a 16 KB file of bytes; no diff of it may hang
this run)."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import scaled

ROOT = Path(__file__).resolve().parents[1]
SECRET = "sk-live-PROBE0123456789abcdef"
GIVEN = "given-on-a-card-0123456789"
SCRIPT = """
import json, subprocess, sys
from pathlib import Path
from app import copies
from app.agent import merge

base = Path(sys.argv[1])
project, runtime = base / "proj", base / "rt"
project.mkdir(); runtime.mkdir()
(project / "config.py").write_text("KEY = None\\n", encoding="utf-8")
(project / "calc.py").write_text("x = 1\\n", encoding="utf-8")
(project / ".gitignore").write_text("out/\\n", encoding="utf-8")
subprocess.run(["git", "init", "-q"], cwd=project, check=True)
copy = copies.make(project, runtime, "probe")
(copy.root / "config.py").write_text(f"KEY = '{sys.argv[2]}'\\n", encoding="utf-8")
(copy.root / "notes.py").write_text(f"TOKEN = '{sys.argv[3]}'\\n", encoding="utf-8")
(copy.root / ".env").write_text("TOKEN=abc\\n", encoding="utf-8")
(copy.root / "blob.bin").write_bytes(bytes(range(256)) * 64)
(copy.root / "out").mkdir()
(copy.root / "out" / "gen.txt").write_text("generated\\n" * 50, encoding="utf-8")
(copy.root / "calc.py").write_text("x = 2\\ny = 3\\n", encoding="utf-8")
copy.secret_held = ("config.py",)
copy.secrets = lambda: (sys.argv[3],)
found = merge.kept_work(copy, "lead")
print(json.dumps([[one.path, one.added, one.removed, one.in_project, diff] for one, diff in found]))
copies.remove(runtime, "probe")
"""


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_the_kept_work_a_look_reads_is_what_take_in_brings_and_no_secret(tmp_path):
    script = tmp_path / "kept.py"
    script.write_text(SCRIPT, encoding="utf-8")
    (tmp_path / "w").mkdir()
    done = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "w"), SECRET, GIVEN],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=scaled(60),
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert done.returncode == 0, done.stderr
    found = {
        path: (added, removed, here, diff)
        for path, added, removed, here, diff in json.loads(done.stdout)
    }
    shown = "".join(diff for *_rest, diff in found.values())
    assert SECRET not in shown and GIVEN not in shown and "TOKEN=abc" not in shown, shown
    assert chr(0xFFFD) not in shown  # (the bytes file: named, not decoded into the diff)
    assert "out/gen.txt" not in found  # (what Take in leaves out: git ignores it)
    for path in ("config.py", "notes.py", ".env", "blob.bin"):
        assert found[path][3] == f"{path}: changed, not shown\n", found[path]
    added, removed, here, diff = found["calc.py"]
    assert (added, removed, here) == (2, 1, True) and "+y = 3" in diff, found["calc.py"]
