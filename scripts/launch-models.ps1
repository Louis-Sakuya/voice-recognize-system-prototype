$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$cli = Join-Path $root ".venv-xinf\Scripts\xinference.exe"
$python = Join-Path $root ".venv-xinf\Scripts\python.exe"
$envFile = Join-Path $root "backend\.env"
$env:XINFERENCE_ENDPOINT = "http://127.0.0.1:9997"

$asrModel = "seaco-paraformer-zh"
$profile = "A"
$modelA = "CosyVoice-300M-SFT"
$modelB = "CosyVoice2-0.5B"

if (Test-Path $envFile) {
  Get-Content $envFile -Encoding utf8 | ForEach-Object {
    if ($_ -match "^\s*#" -or $_ -notmatch "=") { return }
    $name, $value = $_ -split "=", 2
    $name = $name.Trim()
    $value = $value.Trim()
    if ($name -eq "ASR_MODEL" -and $value) { $asrModel = $value }
    if ($name -eq "TTS_PROFILE" -and $value) { $profile = $value.ToUpper() }
    if ($name -eq "TTS_MODEL_A" -and $value) { $modelA = $value }
    if ($name -eq "TTS_MODEL_B" -and $value) { $modelB = $value }
  }
}

if ($profile -notin @("A", "B")) {
  throw "TTS_PROFILE must be A or B, got: $profile"
}
$ttsModel = if ($profile -eq "B") { $modelB } else { $modelA }

function Invoke-Xinf {
  $old = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & $cli @args
    return [int]$LASTEXITCODE
  } finally {
    $ErrorActionPreference = $old
  }
}

function Get-ModelRows {
  $payload = Invoke-RestMethod -TimeoutSec 8 "http://127.0.0.1:9997/v1/models"
  if ($null -eq $payload) { return @() }
  if ($payload.data) { return @($payload.data) }
  if ($payload -is [System.Array]) { return @($payload) }
  return @()
}

function Get-Uid([object]$row) {
  if ($null -eq $row) { return "" }
  foreach ($key in @("id", "model_uid", "model_name", "name")) {
    $value = [string]$row.$key
    if ($value) { return $value }
  }
  return ""
}

function Find-Uids([object[]]$rows, [string]$name) {
  $found = @()
  foreach ($row in @($rows)) {
    $uid = Get-Uid $row
    if (-not $uid) { continue }
    if ($uid -ieq $name -or $uid.StartsWith("$name-", [System.StringComparison]::OrdinalIgnoreCase)) {
      $found += $uid
    }
  }
  return @($found | Select-Object -Unique)
}

function Show-Running {
  $rows = @(Get-ModelRows)
  $uids = @($rows | ForEach-Object { Get-Uid $_ } | Where-Object { $_ })
  if ($uids.Count -eq 0) {
    Write-Host "running models: (none)"
  } else {
    Write-Host ("running models: " + ($uids -join ", "))
  }
  return @($rows)
}

function Remove-ExtraCopies([string]$name) {
  $uids = @(Find-Uids @(Get-ModelRows) $name)
  if ($uids.Count -le 1) { return }
  $keep = @($uids | Where-Object { $_ -ieq $name })
  if ($keep.Count -eq 0) { $keep = @($uids[0]) }
  $keepUid = $keep[0]
  Write-Host "Found $($uids.Count) copies of $name. Keep $keepUid, terminate extras."
  foreach ($uid in $uids) {
    if ($uid -ieq $keepUid) { continue }
    Write-Host "Terminate extra replica: $uid"
    $code = Invoke-Xinf terminate --model-uid $uid
    if ($code -ne 0) {
      Write-Host "terminate $uid failed, exit=$code"
    }
  }
}

function Ensure-OneModel([string]$name, [string]$label) {
  Remove-ExtraCopies $name
  $uids = @(Find-Uids @(Get-ModelRows) $name)
  if ($uids.Count -gt 0) {
    Write-Host "$label already running ($($uids -join ', ')). Skip launch."
    return
  }
  Write-Host "Launch $label : $name (replica=1, uid=$name)"
  $code = Invoke-Xinf launch --model-name $name --model-type audio --replica 1 --model-uid $name --n-worker 1
  if ($code -ne 0) { throw "$label launch failed, exit=$code" }
  $uids = @(Find-Uids @(Get-ModelRows) $name)
  if ($uids.Count -eq 0) {
    throw "$label CLI returned but /v1/models has no $name. Check XINFERENCE_HOME\logs\xinference.log"
  }
  Remove-ExtraCopies $name
}

if (-not (Test-Path $cli)) {
  throw "Missing $cli. Install .venv-xinf first."
}
try {
  $null = Invoke-RestMethod -TimeoutSec 5 "http://127.0.0.1:9997/v1/models"
} catch {
  throw "Xinference is not running at http://127.0.0.1:9997. Start scripts/start-xinference.ps1 first."
}

& $python -c "import hyperpyyaml, onnxruntime, wetext, whisper, conformer, diffusers, einops, omegaconf; print('TTS_DEPS_OK')"
if ($LASTEXITCODE -ne 0) {
  throw "CosyVoice deps missing. In .venv-xinf run: python -m pip install -r backend/requirements-xinf.txt"
}

Write-Host "Launch at most one ASR + one TTS. TTS profile $profile -> $ttsModel"
[void](Show-Running)
Ensure-OneModel $asrModel "ASR"
[void](Show-Running)
Ensure-OneModel $ttsModel "TTS"
Write-Host "---- verify ----"
$rows = Show-Running
if ((@(Find-Uids $rows $asrModel)).Count -eq 0) { throw "ASR not in /v1/models: $asrModel" }
if ((@(Find-Uids $rows $ttsModel)).Count -eq 0) { throw "TTS not in /v1/models: $ttsModel" }
Write-Host "Ready: one ASR + one TTS."
