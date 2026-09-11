$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
Set-Location (Join-Path $root "backend")
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
