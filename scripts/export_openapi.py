import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_settings  # noqa: E402
from app.main import create_app  # noqa: E402

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
    app = create_app(load_settings({"KOLONI_RUNTIME_ROOT": tmp}))
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
