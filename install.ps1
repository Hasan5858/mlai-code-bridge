# Installs mlai-code-bridge as a per-user Scheduled Task (Windows 10/11).
# Run from PowerShell in this folder:  powershell -ExecutionPolicy Bypass -File .\install.ps1
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-Python {
  foreach ($candidate in @('python', 'python3', 'py')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    & $cmd.Source -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { return $cmd.Source }
  }
  throw "Python 3.9+ not found. Install it from python.org and tick 'Add python.exe to PATH'."
}

$py = Find-Python
$state = Join-Path $env:USERPROFILE '.mlai-shim'
$app = Join-Path $state 'app'
New-Item -ItemType Directory -Force -Path $app | Out-Null

# The task runs a copy under %USERPROFILE%\.mlai-shim\app so the repo can live anywhere.
Copy-Item (Join-Path $here 'mlai_bridge.py') (Join-Path $app 'mlai_bridge.py') -Force
Copy-Item (Join-Path $here 'bench.py') (Join-Path $app 'bench.py') -Force
$script = Join-Path $app 'mlai_bridge.py'

# pythonw.exe keeps the console window out of the way.
$exe = $py
$pythonw = Join-Path (Split-Path $py) 'pythonw.exe'
if (Test-Path $pythonw) { $exe = $pythonw }

$action = New-ScheduledTaskAction -Execute $exe -Argument "`"$script`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName 'mlai-code-bridge' -Action $action -Trigger $trigger `
  -Settings $settings -Description 'ML AI Code subscription as an OpenAI-compatible API on 127.0.0.1:8210' `
  -Force | Out-Null
Start-ScheduledTask -TaskName 'mlai-code-bridge'
Start-Sleep -Seconds 3

$keyFile = Join-Path $state 'key'
Write-Host ""
Write-Host "Scheduled task 'mlai-code-bridge' registered and started."
Write-Host "  base_url : http://127.0.0.1:8210/v1"
if (Test-Path $keyFile) { Write-Host "  api_key  : $(Get-Content $keyFile -Raw)" } else { Write-Host "  api_key  : (created on first start, read %USERPROFILE%\.mlai-shim\key)" }
Write-Host "  model    : mlai-code"
Write-Host ""
Write-Host "  health   : curl.exe -s http://127.0.0.1:8210/health"
Write-Host "  logs     : %USERPROFILE%\.mlai-shim\shim.log"
Write-Host "  uninstall: .\uninstall.ps1"
