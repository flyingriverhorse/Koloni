# K-cli-surface (cli-denetim spec section 6): after a CLI updates itself, check that the
# protocol names KOLONI relies on (app/cli_surface.json) are still in it. Local only: no
# model is called, nobody signs in, nothing under ~/.codex, ~/.claude, ~/.copilot or
# ~/.gemini is read, and only versions and missing names are printed. Exit 1: a name is gone.
#
#   powershell -NoProfile -File scripts/cli-surface.ps1
#
# -CodexSchema: a folder of Codex's JSON schema instead of generating it; -Claude, -Copilot,
# -Agy: a file or folder to search instead of the installed CLI (then nothing is run);
# -CopilotExe: the copilot to ask its version of instead of the one on PATH.
#
# Copilot: its version is the one KOLONI runs - asked as KOLONI starts it, with an empty
# COPILOT_HOME and --no-auto-update (the program's own package, not the one it updated itself to
# in your home) - and the names are searched in that package's files under
# %LOCALAPPDATA%\copilot\pkg\win32-x64\<version> (its program, prebuilds\...\runtime.node,
# and its SDK), where they are. (A parameter it does not know is an error: never the real CLI instead.)
[CmdletBinding()]
param(
  [string]$CodexSchema = '',
  [string]$Claude = '',
  [string]$Copilot = '',
  [string]$CopilotExe = '',
  [string]$Agy = '',
  [string]$Surface = ''
)
$ErrorActionPreference = 'Stop'
if (-not $Surface) { $Surface = Join-Path $PSScriptRoot '..\app\cli_surface.json' }
$table = Get-Content -Raw -Encoding UTF8 $Surface | ConvertFrom-Json
$latin1 = [Text.Encoding]::GetEncoding(28591)
$homes = '.codex', '.claude', '.copilot', '.gemini' | ForEach-Object { Join-Path $HOME $_ }
# An npm shim (or Windows' app alias) stands for its package's folder.
$packages = @{ claude = '@anthropic-ai\claude-code'; copilot = '@github\copilot' }
$searched = '.js', '.mjs', '.cjs', '.exe', '.node', '.json'
$gone = $false
$versions = @{}

function Kept-Out($path) {
  foreach ($one in $homes) {
    if ($path.StartsWith($one, [StringComparison]::OrdinalIgnoreCase)) { return $true }
  }
  return $false
}

function Say-Version($cli, $command) {
  $ErrorActionPreference = 'Continue'
  $flags = @('--version')
  $before = $env:COPILOT_HOME
  if ($cli -eq 'copilot') {
    $empty = Join-Path ([IO.Path]::GetTempPath()) ('koloni-copilot-home-' + [guid]::NewGuid())
    New-Item -ItemType Directory $empty | Out-Null
    $env:COPILOT_HOME = $empty
    $flags = @('--no-auto-update', '--version')
  }
  try { $said = "$(& $command @flags 2>$null | Select-Object -First 1)".Trim() }
  finally {
    if ($cli -eq 'copilot') {
      $env:COPILOT_HOME = $before
      Remove-Item -Recurse -Force $empty -ErrorAction SilentlyContinue
    }
  }
  $number = [regex]::Match($said, '\d+(\.\d+)+').Value
  $script:versions[$cli] = $number
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
    $found = if ($cli -eq 'copilot' -and $CopilotExe) { $CopilotExe }
      else { (Get-Command $cli -ErrorAction SilentlyContinue | Select-Object -First 1).Source }
    if (-not $found) { '{0}: not installed' -f $cli; continue }
    Say-Version $cli $found
    $where = $found
    $cache = if ($versions[$cli]) { Join-Path $env:LOCALAPPDATA ('copilot\pkg\win32-x64\' + $versions[$cli]) }
    if ($cli -eq 'copilot' -and $cache -and (Test-Path $cache)) {
      $where = $cache
      '{0}: searching {1} (the package it runs)' -f $cli, $where
    } elseif ($packages.ContainsKey($cli) -and ($where -match '\.(cmd|ps1|bat)$' -or (Get-Item $where).Length -eq 0)) {
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
