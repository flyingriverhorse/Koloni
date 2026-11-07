# Tests and verify

## The full check

```powershell
cd frontend
npx playwright install chromium   # once
cd ..
./scripts/verify.ps1
```

`verify.ps1` stops at the first step that fails. In order:

1. `pytest -q -n auto` (in parallel);
2. `ruff check app tests scripts alembic`;
3. `ty check app`;
4. in `frontend/`: the generated-API-types check, oxlint, the type check, the complexity check, Vitest,
   the build, the guide's checks (below; skipped when Zensical is not installed), and the Playwright
   end-to-end tests.

`-BackendOnly` runs only the first three. On Linux and macOS, run the script with `pwsh`; on Linux,
install Playwright's browser with `--with-deps`.

The parallel test run can load a machine heavily. `PYTEST_XDIST_AUTO_NUM_WORKERS` sets how many processes
`-n auto` starts.

## Complexity

No function may be more complex than 12 (McCabe: 1 plus each branch, loop, case, catch, `?:`, `&&`,
`||` and `??`). Python's gate is ruff's C901 in the `ruff` step: a failure names the function and its
value (`is too complex (14 > 12)`). The frontend's is `npm run check:complexity`
(`frontend/scripts/complexity.mjs`), which fails when a function not in
`frontend/complexity-baseline.json` is over 12, or a baselined one went up; each line gives the file,
line, key (`file::Outer>name`) and value. Split the function; don't raise the limit.

Functions that were already over 12 when the gates came in are debt: a `# noqa: C901` on the `def` line
in Python, an entry in the baseline in the frontend. Both lists only shrink. When a function drops
under 12, delete its `noqa`; the frontend check says `you can lower or remove N baseline entries`, and
`npm run check:complexity -- --update` rewrites the baseline, lowering or dropping entries, never
adding one. Renaming a baselined function makes it look new: rename its key in the baseline by hand.

## End-to-end tests

The Playwright tests start their own KOLONİ and a scripted model server, never a real one. They run with
one worker.

- `KOLONI_E2E_PORT` sets the test KOLONİ's port (9480 by default).
- `FAKE_MODEL_PORT` sets the scripted model server's port (8081 by default); a stand-in llama server
  uses the next port. Two runs at once need model ports at least 2 apart.

## The guide's checks

```powershell
uv pip install -e ".[docs]"                       # Zensical, once
.venv/Scripts/python.exe scripts/check_docs.py    # --no-build: check runtime/site as it is
```

It builds the guide, then fails on a link to a missing page or `#anchor`, a link in `README.md`,
`SECURITY.md` or `CHANGELOG.md` to a missing file, a file a diagram's "From:" line names that is gone,
or a setting the guide's [Settings](../settings.md) and [Every setting](../reference/all-settings.md)
pages name that the app's Settings page does not show (exact text, ignoring case). CI runs it on each push,
and the Pages workflow before it publishes the guide.

### Refreshing the guide's pictures

The guide's screenshots in `docs/images/` and its short videos in `docs/videos/` are taken from the
real app by `frontend/e2e/guide-shots.spec.ts`, with the scripted model, in the light theme: pictures at
1280×800, videos at 1280×720. A video is Playwright's own WebM recording, with a JPEG poster beside
it; a page shows it with a `<video>` tag. The spec is skipped in an ordinary run. To take them again, build first, then from `frontend/`:

```powershell
npm run build
$env:KOLONI_SHOTS = '1'; $env:KOLONI_E2E_PORT = '9500'; $env:FAKE_MODEL_PORT = '9510'
npx playwright test e2e/guide-shots.spec.ts --workers=1
```

A picture or video whose text names a folder of your home fails its test, so neither shows your own
paths. Look at each one before you commit it.

In a page, a video's `src` is written from the page's own file (`../videos/team.webm` in
`docs/agents/teams.md`) and its `poster` from the built page, one folder deeper
(`../../videos/team.jpg`): Zensical rewrites the first and not the second.

## Tests against real things

Tests marked `live` are left out of `verify`:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_live.py -m live
.venv/Scripts/python.exe -m pytest tests/test_docker_executor.py -m live
```

The first needs a model server on port 8080 and, for its CLI tests, signed-in `claude`, `codex` and
`qodercli`. The second needs a Docker daemon and the `alpine` image.

## CI

Each push and pull request to `main` runs the same checks once, on Ubuntu with Python 3.12
(`.github/workflows/pr-check.yml`): pytest, ruff and ty, the API types, the frontend's lint,
typecheck, complexity, unit tests and build, and the guide's checks. A change to the guide or the
plans alone runs only the guide's checks, or nothing.

End-to-end tests, the backend on Windows and on Python 3.13 and 3.14, and the
Docker image run in `heavy.yml`, by hand from the Actions tab, or weekly once the repository
variable `HEAVY_WEEKLY` is `true`. The repository is private and its Actions minutes are counted;
`.github/CI.md` has the table and the reasons.
