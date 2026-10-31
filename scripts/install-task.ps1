param([switch]$Disabled)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ((Get-TimeZone).Id -ne 'China Standard Time') {
    throw 'This task requires the Windows timezone China Standard Time (UTC+8). No timezone was changed.'
}
$pythonPath = (Get-Command python -ErrorAction Stop).Source
if (-not $Disabled) {
    & $pythonPath (Join-Path $projectRoot 'ribao.py') doctor
    if ($LASTEXITCODE -ne 0) { throw 'Configure credentials before enabling the scheduled task.' }
}
$taskName = 'Ribao-Feishu-Daily-0830'
$runnerPath = Join-Path $PSScriptRoot 'run-daily.ps1'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and -not ($existing.Actions | Where-Object { $_.Arguments -like ('*' + $runnerPath + '*') })) {
    throw 'An unrelated scheduled task already uses this name. It was not modified.'
}
$actionArgs = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -PythonPath "{1}"' -f $runnerPath, $pythonPath
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $actionArgs -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At '08:30'
$options = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 45) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $options -Principal $principal -Description 'Bailian qwen-plus: yesterday news, three sections, Feishu delivery. Requires logged-in user, running PC and internet.'
if ($Disabled) { $task.Settings.Enabled = $false }
Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Select-Object TaskName,State
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object NextRunTime,LastTaskResult
