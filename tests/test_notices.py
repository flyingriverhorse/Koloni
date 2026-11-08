import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_notices_list_the_packages_each_with_a_licence(tmp_path):
    out = tmp_path / "NOTICES.md"
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "notices.py"), "--out", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert done.returncode == 0, done.stderr
    text = out.read_text(encoding="utf-8")
    assert "\n### fastapi " in text
    assert "\n### react " in text
    entries = text[text.index("\n### "):text.index("\n## Licence texts")].split("\n### ")[1:]
    assert len(entries) > 200
    missing = [e.splitlines()[0] for e in entries if "\n- Licence: " not in e]
    assert not missing, missing
