Set-Location (Split-Path $PSScriptRoot -Parent)
# Vite's page on 5173 is taken as KOLONİ's own only in development (app/config.py).
$env:KOLONI_DEV = '1'
$env:KOLONI_OPEN_BROWSER = '0'  # the page to work on is Vite's, not the built one on 8790
$backend = Start-Process -PassThru -NoNewWindow .venv/Scripts/python.exe -ArgumentList '-m', 'app.main'
try {
  Push-Location frontend
  npm run dev
} finally {
  Pop-Location
  Stop-Process -Id $backend.Id -Force
  Remove-Item Env:KOLONI_DEV, Env:KOLONI_OPEN_BROWSER  # not for a later start from this shell
}
