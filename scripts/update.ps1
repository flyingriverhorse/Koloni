# Updates this checkout of KOLONİ in one go (0.1.0-guncelleme): the database backed up, the
# code pulled, the Python packages and the page rebuilt. The database itself is migrated when
# KOLONİ next starts. Stop KOLONİ first: on Windows a running one holds its .pyd files and
# `uv pip sync` cannot replace them - the script refuses while something answers on its port.
# shortcut: only KOLONI_PORT is looked at - a KOLONİ on another port, or anything else run
# from this .venv (pytest), still holds its files; check those by hand until it is seen.
# Same steps as scripts/update.sh. -DryRun prints them and runs nothing.
param([switch]$DryRun)

Set-Location (Split-Path $PSScriptRoot -Parent)
$ErrorActionPreference = 'Continue'  # (native tools write progress to stderr; exit codes decide)

$py = if ($env:OS -eq 'Windows_NT') { '.venv/Scripts/python.exe' } else { '.venv/bin/python' }
$port = if ($env:KOLONI_PORT) { [int]$env:KOLONI_PORT } else { 8790 }
$runtime = if ($env:KOLONI_RUNTIME_ROOT) { $env:KOLONI_RUNTIME_ROOT } else { 'runtime' }
$db = Join-Path $runtime 'data/koloni.db'
$backup = Join-Path $runtime "data/backups/koloni-$(Get-Date -Format 'yyyyMMddTHHmmss').db"

function Stop-Update($why) {
  Write-Host "update: $why - stopped, nothing after it ran."
  exit 1
}

function Step($name, [scriptblock]$cmd) {
  Write-Host "== $name"
  if ($DryRun) { return }
  try { & $cmd } catch { Stop-Update "$name failed: $_" }  # (a tool not found)
  if ($LASTEXITCODE -ne 0) { Stop-Update "$name failed" }
}

# B-340: a folder git does not know (a copy made with git archive) cannot be pulled - said in
# words before git says "fatal" on every step after.
git rev-parse --is-inside-work-tree 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Stop-Update 'this folder is not a git checkout; update it with git first (git clone)' }

# A worktree's .venv / node_modules lead to the main checkout's: uv and npm would rewrite those.
$dirs = git rev-parse --path-format=absolute --git-dir --git-common-dir
$linked = ($LASTEXITCODE -eq 0 -and $dirs.Count -eq 2 -and $dirs[0] -ne $dirs[1]) -or
  @('.venv', 'frontend/node_modules' | Where-Object { (Get-Item -Force $_ -ErrorAction SilentlyContinue).LinkType }).Count
if ($linked) { Stop-Update 'this is a linked working copy; run the update in the main checkout' }

if ($DryRun) {
  Write-Host "update (dry run): these steps would run, nothing is run now."
  Write-Host "== refuse if tracked files have changes (git status, runtime/ left out)"
  Write-Host "== refuse while KOLONİ answers on 127.0.0.1:$port"
} else {
  # Untracked files do not stop a fast-forward; changed tracked ones would be in its way.
  $changed = git status --porcelain --untracked-files=no -- . ':(exclude)runtime'
  if ($LASTEXITCODE -ne 0) { Stop-Update 'git status failed (is this a git checkout?)' }
  if ($changed) {
    Write-Host $changed
    Stop-Update 'tracked files have uncommitted changes: commit or stash them first'
  }
  $client = [System.Net.Sockets.TcpClient]::new()
  try { $open = $client.ConnectAsync('127.0.0.1', $port).Wait(1000) } catch { $open = $false }
  $client.Dispose()
  if ($open) { Stop-Update "something answers on 127.0.0.1:$port - stop KOLONİ first (Ctrl+C in its window)" }
}

$backedUp = $null
if ($DryRun -or (Test-Path $db)) {
  # SQLite's own online backup: a consistent copy, the WAL's pages too - never a plain file copy.
  Step "back up the database to $backup" {
    New-Item -ItemType Directory -Force (Split-Path $backup) | Out-Null
    & $py -c 'import sqlite3, sys; s = sqlite3.connect(sys.argv[1]); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()' $db $backup
  }
  $backedUp = $backup
}
# The guide (/guide/) where Zensical is installed: looked at before the sync, which takes it away
# (it is the optional docs extra, not in the lock), then put back and the guide rebuilt.
$zensical = if ($env:OS -eq 'Windows_NT') { '.venv/Scripts/zensical.exe' } else { '.venv/bin/zensical' }
$guide = $DryRun -or (Test-Path $zensical)
Step 'git pull --ff-only' { git pull --ff-only }
Step 'uv pip sync requirements-dev.lock' { uv pip sync --python $py requirements-dev.lock }
Step 'uv pip install --no-deps -e .' { uv pip install --python $py --no-deps -e . }
Step 'npm --prefix frontend ci' { npm --prefix frontend ci }
Step 'npm --prefix frontend run build' { npm --prefix frontend run build }
if ($guide) {
  # (KOLONİ is updated by now: a guide that is not rebuilt is said, and the update ends as usual.)
  Write-Host '== uv pip install -r pyproject.toml --extra docs, then zensical build (the guide at /guide/; a failure only warns)'
  if (-not $DryRun) {
    $built = $false
    try {
      uv pip install --python $py -r pyproject.toml --extra docs
      if ($LASTEXITCODE -eq 0) { & $zensical build; $built = $LASTEXITCODE -eq 0 }
    } catch {}
    if (-not $built) { Write-Host 'update: warning - the guide was not rebuilt (see above); KOLONİ itself is updated.' }
  }
}

if ($DryRun) { exit 0 }
$sha = git rev-parse --short HEAD
$kept = if ($backedUp) { "backup: $backedUp" } else { 'no database yet, nothing backed up' }
Write-Host "Updated to $sha. Restart KOLONİ; the database is migrated when it starts ($kept)."
