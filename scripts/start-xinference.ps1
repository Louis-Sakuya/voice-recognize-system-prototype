$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$xinf = Join-Path $root ".venv-xinf\Scripts\xinference-local.exe"
New-Item -ItemType Directory -Force -Path "D:\Users\Worker\Program\services\xinference" | Out-Null
$env:Path = "D:\Users\Worker\Program\services\ffmpeg\bin;" + $env:Path
$env:XINFERENCE_HOME = "D:\Users\Worker\Program\services\xinference"
$env:XINFERENCE_MODEL_SRC = "modelscope"
$env:XINFERENCE_AUTH_ADVANCED = "0"
$env:XINFERENCE_ENABLE_VIRTUAL_ENV = "0"
& $xinf --host 127.0.0.1 --port 9997
