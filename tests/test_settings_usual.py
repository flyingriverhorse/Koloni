"""Settings' cells (0.1.10) say "the default" where a project's value is what a new project has: the page's
table of those values (frontend/src/shell/sections/usual.ts `USUAL`) is the Project model's column defaults."""

import json
import re
from pathlib import Path

from app.db.models import Project

USUAL = Path(__file__).resolve().parents[1] / "frontend/src/shell/sections/usual.ts"


def _page_defaults() -> dict[str, object]:
    text = USUAL.read_text(encoding="utf-8")
    block = text[text.index("export const USUAL = {") : text.index("} as const")]
    pairs = re.findall(r"^  (\w+): (.+),$", block, re.M)
    return {key: json.loads(value.replace("'", '"')) for key, value in pairs}


def _model_default(name: str) -> object:
    default = Project.__table__.columns[name].default
    if default is None:
        return None
    return default.arg(None) if callable(default.arg) else default.arg


def test_every_default_the_page_says_is_the_model_s():
    page = _page_defaults()
    assert len(page) > 30, page
    for name, value in page.items():
        assert _model_default(name) == value, name
