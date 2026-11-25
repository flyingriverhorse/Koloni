# Runs every check for the repo: backend tests, lint, dead code and types, then the
# frontend's generated-types check, lint, typecheck, unit tests, build, the guide's checks and e2e.
# -BackendOnly: the backend's only.
param([switch]$BackendOnly)
Set-Location (Split-Path $PSScriptRoot -Parent)

function Step($name, [scriptblock]$cmd) {
  Write-Host "== $name"
  # Native tools write progress to stderr; only the exit code decides failure.
  $ErrorActionPreference = 'Continue'
  & $cmd
  if ($LASTEXITCODE -ne 0) {
    Write-Host "verify: FAILED at $name"
    exit 1
  }
}

# $env:OS is Windows_NT under both Windows PowerShell 5.1 and pwsh, unset on Linux and macOS.
$py = if ($env:OS -eq 'Windows_NT') { '.venv/Scripts/python.exe' } else { '.venv/bin/python' }
# This checkout's own environment, whatever the shell had: ty takes VIRTUAL_ENV for it, and
# one inherited from another repository's shell had it check against that one's packages.
$env:VIRTUAL_ENV = (Resolve-Path .venv).Path
# In parallel (pytest-xdist): 4040 tests in 7 min with 8 workers, against 25 one by one (24 Oct).
# The 25 slowest tests are listed at the end: where the time goes, in every log.
Step 'pytest' { & $py -m pytest -q -n auto --durations=25 }
Step 'ruff'   { & $py -m ruff check app tests scripts alembic }
Step 'file size' { & $py scripts/check_file_size.py }
Step 'ty'     { & $py -m ty check app }
# vulture and Pyrefly are CI's and the maintainers' own (requirements-lint.lock), never in an
# install: missing, the step fails with how to install them.
function Lint([string]$tool, [string[]]$arguments) {
  & $py -c "import importlib.util, sys; sys.exit(importlib.util.find_spec('$tool') is None)"
  if ($LASTEXITCODE -ne 0) {
    Write-Host 'install the lint tools: uv pip install -r requirements-lint.lock'
    return
  }
  & $py -m $tool @arguments
}
Step 'vulture' { Lint vulture @() }
Step 'pyrefly' { Lint pyrefly @('check', '--python-interpreter-path', $py, '--min-severity', 'warn') }
if (-not $BackendOnly -and (Test-Path frontend/package.json)) {
  Set-Location frontend
  Step 'api types' { npm run check:api }
  Step 'lint'      { npm run lint }
  Step 'typecheck' { npm run typecheck }
  Step 'complexity' { npm run check:complexity }
  Step 'vitest'    { npm test }
  Step 'build'     { npm run build }
  # The guide's checks, where Zensical is installed (the docs extra); CI's docs-check.yml always runs them.
  if (Test-Path (Join-Path (Split-Path "../$py") 'zensical*')) {
    Step 'docs'    { & "../$py" ../scripts/check_docs.py }
  } else {
    Write-Host '== docs: skipped, Zensical is not installed (uv pip install -e ".[docs]")'
  }
  Step 'e2e'       { npm run e2e }
}
Write-Host 'verify: OK'
