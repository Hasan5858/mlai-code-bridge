# Stops and removes the mlai-code-bridge Scheduled Task. State stays in %USERPROFILE%\.mlai-shim.
$ErrorActionPreference = 'Stop'
Unregister-ScheduledTask -TaskName 'mlai-code-bridge' -Confirm:$false
Write-Host "removed scheduled task 'mlai-code-bridge'"
