"""N9 (the second session, 27 Nov): after an agent wrote `evil096.npmrc`, the card of `npm exec tsc
-- --noEmit --pretty false` said "an agent wrote its program (evil096.npmrc)" - a file the line does
not run. A node runner's rule still stops at any `.npmrc` / `x.npmrc` an agent wrote (npm reads one
it is pointed at), and the card says what it is: a file the line may read or load."""

import pytest

from app.cards import PLANTED, PLANTED_READ
from app.command_runner import _planted
from tests.test_proof_style import _copy_db


@pytest.mark.parametrize(
    ("line", "cwd", "written", "said", "place"),
    [
        ("npm exec tsc -- --noEmit --pretty false", ".", "evil096.npmrc", PLANTED_READ, None),
        # (a runner's own place that is a setting: the folder's `.npmrc`, yarn's `.yarnrc.yml`)
        ("npm exec tsc -- --noEmit", "web", "web/.npmrc", PLANTED_READ, None),
        ("yarn tsc --noEmit", ".", ".yarnrc.yml", PLANTED_READ, None),
        # (what it runs is still its program: an install folder's file, said by the folder)
        ("npx tsc --noEmit", ".", "node_modules/typescript/bin/tsc", PLANTED, "node_modules"),
    ],
)
def test_a_card_names_a_setting_an_agent_wrote_as_one_the_line_may_read(  # noqa: PLR0913
    tmp_path, line, cwd, written, said, place
):
    factory = _copy_db(tmp_path, {written: "node-options=--require ./evil096.js\n"})
    root = (tmp_path / "copy").resolve()
    (root / cwd).mkdir(parents=True, exist_ok=True)
    assert _planted(factory, "c", root, line, cwd) == said.format(place=place or written)
    # (its card offers no rule: `test_proof_style`'s `other096/evil096.npmrc`, on the page)
