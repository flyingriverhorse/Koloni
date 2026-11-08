# CI

The repository is public, so GitHub's standard runners cost nothing. Each pull request to `main`
runs PR Check (Linux, Python 3.12) and the heavy set (e2e, Windows, Python 3.13 / 3.14) side by
side: together they are the full verify, on GitHub's machines rather than yours.
`scripts/verify.ps1` still runs everything locally when you want it.

| When | Workflow | What |
|---|---|---|
| Each push and pull request to `main` | `pr-check.yml` | actionlint on every workflow; `backend.yml` (pytest in six parallel parts; ruff, ty and `check:api` in a seventh); `frontend.yml` (lint, typecheck, complexity, vitest, build); `docs-check.yml` (the guide's checks); the SonarQube Cloud scan, only when the secret `SONAR_TOKEN` is set. A newer push to the same branch cancels the older run, except on `main` |
| A push or pull request that changes only `docs/` (but `docs/settings.md`, which a test reads), `pages/`, README / SECURITY / CHANGELOG and the like | `docs-check.yml` alone when the guide or one of those three changed; otherwise nothing | `pr-check.yml`'s `paths` list what is skipped |
| Each pull request to `main` (same `paths` as PR Check); weekly (Mondays 03:30 UTC), only when the repository variable `HEAVY_WEEKLY` is `true`; by hand on any branch | `heavy.yml` | e2e (Playwright, Ubuntu, in three shards); `backend.yml`'s pytest parts on Windows (Python 3.12, twelve parts) and on Ubuntu (six) with Python 3.13 and 3.14 (no lint part: PR Check lints); the Docker image build (by hand only, tick `docker`) |
| Each pull request to `main` (same `paths` as PR Check); by hand on any branch | `macos.yml` | `backend.yml`'s six pytest parts on macOS (Python 3.12). Apart from PR Check while macOS is new: a failure shows on the pull request but holds neither a merge nor a release |
| By hand, on any branch, no pull request needed | `full.yml` (Full check) | PR Check, the heavy set and macOS together, the same jobs a pull request runs (`gh workflow run full.yml --ref <branch>`; `-f docker=true` adds the image) |
| By hand; on a push to `main` that changes the guide or `pages/` once the variable `PAGES_ENABLED` is `true` | `docs.yml` | Builds and checks the guide, then (from `main` only) pushes the site to the `gh-pages` branch: `pages/` at the root (`README.md` left out), the guide under `manual/`. See GitHub Pages below |
| Each push and pull request to `main` (not one that changes only the guide or notes), weekly (Mondays 07:00 UTC), by hand; only when the variable `CODE_SECURITY` is `true` | `codeql.yml` | CodeQL code scanning of Python and JavaScript/TypeScript, from source (no install, no build); `.github/codeql-config.yml` leaves out tests, the guide, generated and vendored files. Results under Security → Code scanning |
| A pull request that changes `pyproject.toml`, `requirements-dev.lock`, `frontend/package*.json` or a workflow; only when `CODE_SECURITY` is `true` | `dependency-review.yml` | Fails the pull request when it adds a dependency with a known high or critical vulnerability |
| Weekly (Mondays 06:00 UTC); by hand | `security.yml` | `pip-audit` on `requirements-dev.lock` and `npm audit --omit=dev` on `frontend/package-lock.json`; reads the lock files, installs nothing. A finding fails the run |
| Each pull request | `labeler.yml` | Labels it by the paths it changes (`.github/labeler.yml`): backend, migrations, frontend, tests, docs, ci, dependencies |
| A push to `main` that changes `CHANGELOG.md` or `pyproject.toml`; by hand | `release-drafter.yml` | Keeps a draft release `v<version>` with the notes from `CHANGELOG.md` (`.github/scripts/release_notes.py --draft`: the version's section, or `[Unreleased]` until it is cut) |
| Each push to `main` (stops in seconds unless release-ready); a pushed tag `v*`; by hand | `release.yml` | A `gate` job: on `main`, goes on only when `pyproject.toml`'s version has no tag `v<version>` yet and `CHANGELOG.md` has a dated `## [X.Y.Z] - YYYY-MM-DD` section with entries (`release_notes.py --ready`). Then checks the tag is `v` + that version and the changelog has its dated section; ruff, ty, the frontend's lint and build; publishes the GitHub Release (the draft if there is one) with the notes and the source plus `frontend/dist` as `.tar.gz` and `.zip`, with `SHA256SUMS`, once that commit's PR Check run on `main` has passed (a warning when its paths skipped it); from `main` it first creates the tag `v<version>` at the pushed commit |
| Weekly | Dependabot (`.github/dependabot.yml`) | Update pull requests for pip (`pyproject.toml`), npm (`frontend/`) and GitHub Actions; minor and patch grouped into one pull request per ecosystem |

`backend.yml`, `frontend.yml` and `docs-check.yml` can each be started alone from the Actions tab
(Run workflow); `backend.yml` takes the Python version, the runner (`os`), whether to lint and
whether to measure coverage.

**The heavy set by hand:** Actions → Heavy → Run workflow, on the branch you want, with no pull
request needed. With the GitHub CLI: `gh workflow run heavy.yml --ref <branch>` (add
`-f docker=true` for the image). A workflow can be started by hand only once it is on `main`.

**Minutes.** The old `ci.yml` ran the full verify on Windows and Ubuntu × Python 3.12, 3.13 and 3.14
on every push: six jobs that each reached their 45-minute limit, about 400 billed minutes a push.
On one Ubuntu runner pytest alone took 42 minutes (run 42038019264), so `backend.yml` splits it into
six parts (`.github/scripts/test_parts.py`: each test file in exactly one part, the largest first
into the part with the fewest bytes so far, so the parts take about as long), each limited to 20
minutes (30 on Windows). That shortens the wait (about 10 minutes instead of 17 with three parts),
not the bill: a push costs about 70 billed minutes (pytest's ~45 spread over six runners, plus each
runner's ~2 minutes of setup, the lint part, the frontend, the guide and actionlint). More parts
would add setup minutes faster than they cut the wait. With `SONAR_TOKEN` set, coverage slows the
parts a little and the scan adds a few minutes: about 85. CodeQL, once on, adds about 10.

The heavy set is about 460 billed minutes: e2e ~27 (three shards with Playwright's `--shard`, each
with ~4 minutes of setup beside its share of the tests; failures kept as `e2e-failures-1` … `-3`),
the two Ubuntu backends ~57 each, and the Windows backend ~160 counted twice. So it stays off the
schedule until `HEAVY_WEEKLY` is set. The six-part and three-shard figures are estimates from run
42038019264; correct them after the first runs.

**Windows is several times slower.** In run 42408875343 its six parts took 18–24 minutes of tests
each (Ubuntu: 4–5), two reached the 30-minute limit, and one fresh migration took 60 s (2 s on a
desktop): the runner's disk, not the four xdist workers, which Ubuntu has too. So Windows runs
twelve parts, each still limited to 30 minutes, with the tests' temporary files on the checkout's
disk (`TMP` = `RUNNER_TEMP`, D:). Whether twelve parts fit and D: is faster is to be seen in the
next runs. On any CI runner (`CI` set) the tests' shared waits (`wait_run`, `Gate.wait_partial`,
`tests/test_parallel.py`'s `until`) last 4× longer, 10× on Windows, but at most 3 minutes unless
already longer (`scaled` in `tests/conftest.py`): a ceiling for something that does happen, so a
passing test waits no longer, and a real failure still fails as itself before the part's limit.

**Known failures on Linux.** The last run of the old `ci.yml` on Ubuntu (3.12) had 15 failed tests
of 8,140, for example `tests/test_triggers.py::test_the_servers_access_log_never_holds_a_webhooks_key`
(`httpx.ReadTimeout`). Until they are fixed, the backend job is red on every push.

**Windows runs Python 3.12 only.** No job runs Windows on 3.13 or 3.14, where `os.path.isabs`
no longer calls `/x` absolute (the path checks add `PureWindowsPath(...).anchor`;
`tests/test_branches.py` patches in the 3.13 rule). Try a change to a Windows path check on a
newer Python by hand (`py -3.14`).

**What to turn on in GitHub** (Settings of the repository):

- **Code scanning and dependency review** need GitHub Code Security on a private repository (on a
  public one they are free). Once it is on (Settings → Advanced Security), set the repository
  variable `CODE_SECURITY` to `true` (Settings → Secrets and variables → Actions → Variables);
  until then `codeql.yml` and `dependency-review.yml` skip their jobs and use no minutes. Leave
  CodeQL's *default setup* off (Settings → Advanced Security → CodeQL analysis): while it is on,
  GitHub rejects the results `codeql.yml` (an advanced setup) uploads, and its jobs fail.
- **Dependabot**: Settings → Advanced Security → Dependabot alerts and security updates on;
  version updates run from `.github/dependabot.yml` by themselves. Dependabot updates
  `pyproject.toml` but cannot rebuild `requirements-dev.lock` (compiled on Windows), so its pull
  request fails `backend.yml`'s lint part (`.github/scripts/check_lock.py`: every requirement of
  `pyproject.toml` and its dev extra must accept the locked version) until you run the command in
  the lock's header on its branch and push the lock. Then the tests run on the new version.
- **GitHub Pages** (the site https://koloni.skyulf.com, `docs.yml`): Settings → Pages → Source:
  **Deploy from a branch**, branch `gh-pages`, folder `/ (root)` (the branch appears after the first
  run: Actions → Guide → Run workflow on `main`). Custom domain `koloni.skyulf.com`, then **Enforce
  HTTPS** once the certificate is issued. DNS at the `skyulf.com` provider: a `CNAME` record
  `koloni` → `flyingriverhorse.github.io`. To keep anyone else from claiming the domain, verify
  `skyulf.com` under the account's Settings → Pages → Verified domains. The guide is at `/manual/`
  (`zensical.toml`'s `site_url`); the landing page (`pages/index.html` and `pages/assets/`) is
  at the root. Each run replaces the branch with one commit
  (`force_orphan`), so `pages/CNAME` must stay: without it a publish drops the custom domain. Then
  set the variable `PAGES_ENABLED` to `true` to publish on every push that changes the guide. On a
  private repository Pages needs a paid plan, and the published site is public.
- **Discussions** (Settings → General → Features), which `.github/SUPPORT.md` points to.
- **Releases** need nothing more: `release-drafter.yml` and `release.yml` use the run's own
  `GITHUB_TOKEN` with `contents: write` on the one job that writes. To release: set the version in
  `pyproject.toml`, move the `[Unreleased]` entries under `## [X.Y.Z] - YYYY-MM-DD`, and merge to
  `main`; the release and its tag `vX.Y.Z` (at the merge commit) come out by themselves. Check the
  notes first with `python .github/scripts/release_notes.py --ready`. Pushing a tag by hand
  (`git tag vX.Y.Z && git push origin vX.Y.Z`) still works. `release.yml` refuses a tag on a commit
  that is not on `main`, never moves an existing tag and never replaces a release already
  published. The full suite runs in `scripts/verify.ps1` locally and in the pull request's checks;
  the publish job also waits (up to 40 minutes) for the commit's own PR Check run on `main` and
  stops, before tagging, if it failed; a commit PR Check's paths skip (only the changelog, say)
  publishes with a warning. A failed run is safe to repeat with Re-run all jobs within GitHub's
  30-day re-run window (a tag already at its commit is reused, a published release left alone);
  after that, run the workflow by hand on the tag (Run workflow, pick the tag) instead. A newer push
  can cancel a pending PR Check on `main`; that commit's release run then fails with no tag, which
  is harmless, since the newer push's run releases. Recommended: a tag ruleset (Settings → Rules → Rulesets → New tag
  ruleset, target `v*`, restrict updates and deletions, bypass: repository admins), so no one moves
  or deletes a `v*` tag. Do not restrict creations unless the ruleset can list GitHub Actions as a
  bypass actor: the workflow creates the tag with `GITHUB_TOKEN`.
- **SonarQube Cloud** (`sonar-project.properties`, the `sonar` job in `pr-check.yml`): import the
  repository as a project on [sonarcloud.io](https://sonarcloud.io) under the organization
  `flyingriverhorse`, key `flyingriverhorse_Koloni` (or change both in
  `sonar-project.properties`); in the project, Administration → Analysis Method → turn
  Automatic Analysis off (it clashes with the CI scan); create a token (My Account → Security)
  and add it as the repository secret `SONAR_TOKEN` (Settings → Secrets and variables → Actions →
  Secrets). Without the secret the gate job skips the scan and the backend measures no coverage.
  Check whether SonarQube Cloud's free plan covers a private repository of this size or a paid
  plan is needed (it is free for public ones). Coverage: each
  pytest part measures `app/` (pytest-cov, installed in CI only) into `.coverage.part-N`, kept as an
  artifact; the scan job combines all six into `coverage-backend.xml` (paths `app/…`) and fails if
  a part is missing. The frontend is analysed without coverage (no vitest coverage package yet).
  Locally: install SonarQube for IDE (SonarLint) in VS Code and bind it to the project in connected
  mode (a SonarQube Cloud connection with your own token, then *Bind to project*), so the editor
  shows the same rules and suppressions.
- `security.yml` scans the lock as written; the lock is compiled on Windows, so Linux-only
  packages (uvloop) are not in it and not scanned.

**Left out on purpose:** Codacy (needs an external account and token; SonarQube Cloud covers it)
and `FUNDING.yml` (whether and where to take sponsorship is the owner's choice). No PyPI upload or container push either;
`release.yml` notes where they would go.

**actionlint locally:** `actionlint -shellcheck= -pyflakes=` from the repository root (1.7.12,
the version CI pins with its SHA-256).
