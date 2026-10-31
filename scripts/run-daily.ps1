param([Parameter(Mandatory=$true)][string]$PythonPath)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$logFolder = Join-Path $projectRoot 'data\logs'
New-Item -ItemType Directory -Path $logFolder -Force | Out-Null
$logPath = Join-Path $logFolder ((Get-Date -Format 'yyyy-MM-dd-HHmmss') + '.log')
Push-Location -LiteralPath $projectRoot
try {
    $env:PYTHONUTF8 = '1'
    # Use native process output without PowerShell converting stderr to a terminating error.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $PythonPath (Join-Path $projectRoot 'ribao.py') run *> $logPath
    $runExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousPreference
} finally {
    Pop-Location
}
exit $runExitCode
