# Puts this checkout's HEAD into a separate live copy of KOLONİ and restarts it there (the REA
# agent's live-test copy: AGENTS.md "REA ajanı"): the page built, the tree exported with
# `git archive`, the copy's database backed up, the old tree swapped out, the server started
# again on the copy's own port and runtime. It never touches this checkout's runtime or the
# port KOLONİ itself runs on (8790): both are refused. -DryRun prints the steps and runs nothing.
#
#   scripts\canli.ps1 [-Copy C:\Users\Murat\koloni-canli] [-Port 8791] [-NoBuild] [-DryRun]
#
# The copy holds: key.txt (its page key), runtime\ (its data), .venv\ (its own), serverNN.log.
# shortcut: the copy's venv is not synced with the lockfile; run `uv sync` there by hand when
# pyproject changes - make it a step if that is forgotten once.
param(
  [string]$Copy = 'C:\Users\Murat\koloni-canli',
  [int]$Port = 8791,
  [switch]$NoBuild,
  [switch]$DryRun
)

Set-Location (Split-Path $PSScriptRoot -Parent)
$ErrorActionPreference = 'Continue'
$checkout = (Get-Location).Path
$Copy = $Copy.TrimEnd('\')

function Stop-Canli($why) {
  Write-Host "canli: $why - stopped, nothing after it ran."
  exit 1
}

function Step($name, [scriptblock]$cmd) {
  Write-Host "== $name"
  if ($DryRun) { return }
  try { & $cmd } catch { Stop-Canli "$name failed: $_" }
  if ($LASTEXITCODE) { Stop-Canli "$name failed" }
}

# Never the checkout itself, never the user's own KOLONİ.
if ($Port -eq 8790) { Stop-Canli 'port 8790 is the user''s own KOLONİ' }
if ([IO.Path]::GetFullPath($Copy).TrimEnd('\') -eq $checkout) { Stop-Canli 'the copy must not be this checkout' }
if (-not (Test-Path "$Copy\key.txt") -or -not (Test-Path "$Copy\.venv\Scripts\python.exe")) {
  Stop-Canli "$Copy is not a live copy (key.txt and .venv\Scripts\python.exe expected)"
}
$py = "$Copy\.venv\Scripts\python.exe"
$db = "$Copy\runtime\data\koloni.db"
$newest = (Get-ChildItem alembic\versions\*.py | Sort-Object Name | Select-Object -Last 1).Name.Substring(0, 4)
$sha = git rev-parse --short HEAD
# Named after the newest migration it is taken before, and the tree: a backup a run makes is
# never written over by a later run (the one before a migration is what the fixtures come from).
$backup = "$Copy\koloni-before-$newest-$sha.db"
$log = "$Copy\server-$sha.log"
if ($DryRun) { Write-Host "canli (dry run): these steps would run, nothing is run now." }

if (-not $NoBuild) { Step 'npm --prefix frontend run build' { npm --prefix frontend run build } }

Step "stop the copy's server (python -m app.main under $Copy)" {
  Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and $_.CommandLine -like "*$Copy\.venv*" -and $_.CommandLine -like '*app.main*'
  } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
  Start-Sleep 3
  $global:LASTEXITCODE = 0
}

if ($DryRun -or (Test-Path $db)) {
  # SQLite's own online backup, the WAL's pages too (as scripts/update.ps1 does).
  Step "back up the copy's database to $backup" {
    & $py -c 'import sqlite3, sys; s = sqlite3.connect(sys.argv[1]); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()' $db $backup
  }
}

Step "export HEAD ($sha) to $Copy\src.new and put the built page in it" {
  if (Test-Path "$Copy\src.new") { Remove-Item -Recurse -Force "$Copy\src.new" }
  New-Item -ItemType Directory "$Copy\src.new" | Out-Null
  git archive HEAD | tar -x -C "$Copy\src.new"
  if ($LASTEXITCODE) { return }
  Copy-Item -Recurse frontend\dist "$Copy\src.new\frontend\dist"
}

# The guide (/guide/, runtime\site): not in git, so built in the new tree with this checkout's
# Zensical where it is installed. A failure only warns: the copy runs, without its guide.
$zensical = "$checkout\.venv\Scripts\zensical.exe"
if (Test-Path $zensical) {
  Write-Host "== build the guide in $Copy\src.new (zensical build; a failure only warns)"
  if (-not $DryRun) {
    Push-Location "$Copy\src.new"
    & $zensical build
    if ($LASTEXITCODE) { Write-Host 'canli: warning - the guide was not built; /guide/ is missing in the copy.' }
    Pop-Location
    $global:LASTEXITCODE = 0
  }
}

Step "swap it in (the old tree kept as src.old)" {
  if (Test-Path "$Copy\src.old") { Remove-Item -Recurse -Force "$Copy\src.old" }
  if (Test-Path "$Copy\src") { Rename-Item "$Copy\src" "$Copy\src.old" }
  Rename-Item "$Copy\src.new" "$Copy\src"
  $sha | Set-Content "$Copy\HEAD.txt"
  $global:LASTEXITCODE = 0
}

Step "start the copy's server on 127.0.0.1:$Port (log $log)" {
  $key = (Get-Content "$Copy\key.txt" -Raw).Trim()
  $cmd = "`$env:KOLONI_RUNTIME_ROOT='$Copy\runtime'; `$env:KOLONI_PORT='$Port'; `$env:KOLONI_PAGE_KEY='$key'; `$env:KOLONI_OPEN_BROWSER='0'; " +
    "Set-Location '$Copy\src'; & '$py' -m app.main *>> '$log'"
  $p = Start-Process pwsh -ArgumentList '-NoProfile', '-Command', $cmd -WindowStyle Hidden -PassThru
  $p.Id | Set-Content "$Copy\pid_nogit.txt"
  $up = $false
  foreach ($i in 1..30) {
    Start-Sleep 2
    try {
      $r = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/health" -Headers @{ 'x-koloni-key' = $key } -TimeoutSec 3
      if ($r.StatusCode -eq 200) { $up = $true; break }
    } catch {}
  }
  if (-not $up) { Stop-Canli "the server did not answer on $Port within 60 s - see $log" }
  $global:LASTEXITCODE = 0
}

if ($DryRun) { exit 0 }
Write-Host "Live copy at $sha (migrations up to $newest) on http://127.0.0.1:$Port/ - backup $backup."
