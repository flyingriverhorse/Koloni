# K-cli-surface (cli-denetim spec section 6): after a CLI updates itself, check that the
# protocol names KOLONI relies on (app/cli_surface.json) are still in it. Local only: no
# model is called, nobody signs in, nothing under ~/.codex, ~/.claude, ~/.copilot or
# ~/.gemini is read, and only versions and missing names are printed. Exit 1: a name is gone.
#
#   powershell -NoProfile -File scripts/cli-surface.ps1
#
# -CodexSchema: a folder of Codex's JSON schema instead of generating it; -Claude, -Copilot,
# -Agy: a file or folder to search instead of the installed CLI (then nothing is run).
param(
  [string]$CodexSchema = '',
  [string]$Claude = '',
  [string]$Copilot = '',
  [string]$Agy = '',
  [string]$Surface = (Join-Path $PSScriptRoot '..\app\cli_surface.json')
)
$ErrorActionPreference = 'Stop'
$table = Get-Content -Raw -Encoding UTF8 $Surface | ConvertFrom-Json
$latin1 = [Text.Encoding]::GetEncoding(28591)
$homes = '.codex', '.claude', '.copilot', '.gemini' | ForEach-Object { Join-Path $HOME $_ }
# An npm shim (or Windows' app alias) stands for its package's folder.
$packages = @{ claude = '@anthropic-ai\claude-code'; copilot = '@github\copilot' }
$searched = '.js', '.mjs', '.cjs', '.exe', '.node', '.json'
$gone = $false

function Kept-Out($path) {
  foreach ($one in $homes) {
    if ($path.StartsWith($one, [StringComparison]::OrdinalIgnoreCase)) { return $true }
  }
  return $false
}

function Say-Version($cli, $command) {
  $ErrorActionPreference = 'Continue'
  $said = "$(& $command --version 2>$null | Select-Object -First 1)".Trim()
  $number = [regex]::Match($said, '\d+(\.\d+)+').Value
  $how = if ($table.$cli.measured -contains $number) { 'measured' } else { 'NOT measured' }
  '{0}: version {1} ({2}; measured: {3})' -f $cli, $said, $how, ($table.$cli.measured -join ', ')
}

function Missing($files, $names) {
  # Each file read in pieces, as Latin-1 bytes: a name split between two pieces is still seen.
  $left = New-Object 'System.Collections.Generic.List[string]'
  foreach ($name in $names) { $left.Add($name) }
  $keep = ($names | Measure-Object -Property Length -Maximum).Maximum
  $buffer = New-Object byte[] (16MB)
  foreach ($file in $files) {
    $stream = [IO.File]::OpenRead($file)
    try {
      $tail = ''
      while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
        $text = $tail + $latin1.GetString($buffer, 0, $read)
        foreach ($name in @($left)) { if ($text.Contains($name)) { [void]$left.Remove($name) } }
        if ($left.Count -eq 0) { return @() }
        $tail = $text.Substring([Math]::Max(0, $text.Length - $keep))
      }
    } finally { $stream.Dispose() }
  }
  return @($left)
}

function Report($cli, $missing) {
  if ($missing.Count -eq 0) {
    '{0}: all {1} names found' -f $cli, @($table.$cli.names).Count
  } else {
    $script:gone = $true
    foreach ($name in $missing) { '{0}: missing {1}' -f $cli, $name }
  }
}

# Codex: its own schema of the app-server protocol, generated locally.
$schema = $CodexSchema
$made = $null
if (-not $schema) {
  if (Get-Command codex -ErrorAction SilentlyContinue) {
    Say-Version 'codex' 'codex'
    $made = Join-Path ([IO.Path]::GetTempPath()) ('koloni-codex-schema-' + [guid]::NewGuid())
    $ErrorActionPreference = 'Continue'
    & codex app-server generate-json-schema --experimental --out $made 2>$null | Out-Null
    $ErrorActionPreference = 'Stop'
    $schema = $made
  } else { 'codex: not installed' }
}
if ($schema) {
  $files = @(Get-ChildItem $schema -Recurse -File -Filter *.json -ErrorAction SilentlyContinue |
    ForEach-Object { $_.FullName })
  if ($files.Count -eq 0) { $gone = $true; 'codex: no schema was written' }
  else { Report 'codex' (Missing $files $table.codex.names) }
  if ($made) { Remove-Item -Recurse -Force $made -ErrorAction SilentlyContinue }
}

# Claude Code, Copilot, agy: the names searched for in their installed files.
foreach ($cli in 'claude', 'copilot', 'agy') {
  $where = @{ claude = $Claude; copilot = $Copilot; agy = $Agy }[$cli]
  if (-not $where) {
    $found = Get-Command $cli -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $found) { '{0}: not installed' -f $cli; continue }
    Say-Version $cli $found.Source
    $where = $found.Source
    if ($packages.ContainsKey($cli) -and ($where -match '\.(cmd|ps1|bat)$' -or (Get-Item $where).Length -eq 0)) {
      $where = Join-Path $env:APPDATA ('npm\node_modules\' + $packages[$cli])
      $manifest = Join-Path $where 'package.json'
      if (Test-Path $manifest) {
        # (Copilot updates its program in place: the package's own number can be older.)
        '{0}: searching {1} (package {2})' -f $cli, $where, (Get-Content -Raw $manifest | ConvertFrom-Json).version
      }
    }
  }
  if (-not (Test-Path $where)) { $gone = $true; '{0}: not checked, {1} is not there' -f $cli, $where; continue }
  if (Kept-Out ((Resolve-Path $where).Path)) { '{0}: not checked, its files are in a folder KOLONI does not read' -f $cli; continue }
  $files = @(Get-ChildItem $where -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $searched -contains $_.Extension -and -not (Kept-Out $_.FullName) } |
    ForEach-Object { $_.FullName })
  Report $cli (Missing $files $table.$cli.names)
}
if ($gone) { exit 1 }
