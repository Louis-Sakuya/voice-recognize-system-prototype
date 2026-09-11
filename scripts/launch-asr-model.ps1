$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$cli = Join-Path $root ".venv-xinf\Scripts\xinference.exe"
$env:XINFERENCE_ENDPOINT = "http://127.0.0.1:9997"
& $cli launch --model-name paraformer-zh --model-type audio
& $cli list
