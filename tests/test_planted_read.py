"""N9 (the second session, 27 Nov): after an agent wrote `evil096.npmrc`, the card of `npm exec tsc
-- --noEmit --pretty false` said "an agent wrote its program (evil096.npmrc)" - a file the line does
not run. A node runner's rule still stops at any `.npmrc` / `x.npmrc` an agent wrote (npm reads one
it is pointed at), and the card says what it is: a file the line may read or load."""

import pytest

from app.cards import PLANTED, PLANTED_READ
from app.command_runner import _planted
from tests.test_proof_style import _copy_db

TSC = "node_modules/typescript/bin/tsc"
RUFF = ".venv/Scripts/ruff.exe"


@pytest.mark.parametrize(
    ("line", "cwd", "written", "said"),
    [
        (
            "npm exec tsc -- --noEmit --pretty false",
            ".",
            ["evil096.npmrc"],
            PLANTED_READ.format(place="evil096.npmrc"),
        ),
        # (a runner's own place that is a setting: the folder's `.npmrc`, yarn's `.yarnrc.yml`)
        (
            "npm exec tsc -- --noEmit",
            "web",
            ["web/.npmrc"],
            PLANTED_READ.format(place="web/.npmrc"),
        ),
        ("yarn tsc --noEmit", ".", [".yarnrc.yml"], PLANTED_READ.format(place=".yarnrc.yml")),
        # (what it runs is its program: an install folder's file, yarn's own release in `.yarn`)
        ("npx tsc --noEmit", ".", [TSC], PLANTED.format(place="node_modules")),
        ("yarn tsc --noEmit", ".", [".yarn/releases/yarn-4.cjs"], PLANTED.format(place=".yarn")),
        # (a setting and the program both written: the program is said, whichever came first)
        ("npx tsc --noEmit", ".", ["package.json", TSC], PLANTED.format(place="node_modules")),
        ("npx tsc --noEmit", ".", [TSC, "package.json"], PLANTED.format(place="node_modules")),
        ("uv run ruff check .", ".", ["pyproject.toml", RUFF], PLANTED.format(place=".venv")),
        ("uv run ruff check .", ".", [RUFF, "pyproject.toml"], PLANTED.format(place=".venv")),
    ],
)
def test_a_card_names_a_setting_an_agent_wrote_as_one_the_line_may_read(
    tmp_path, line, cwd, written, said
):
    factory = _copy_db(tmp_path, dict.fromkeys(written, "node-options=--require ./evil096.js\n"))
    root = (tmp_path / "copy").resolve()
    (root / cwd).mkdir(parents=True, exist_ok=True)
    assert _planted(factory, "c", root, line, cwd) == said
    # (its card offers no rule: `test_proof_style`'s `other096/evil096.npmrc`, on the page)
