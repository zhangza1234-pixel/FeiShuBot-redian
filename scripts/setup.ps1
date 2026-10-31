param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonPath = (Get-Command python -ErrorAction Stop).Source
if ($CheckOnly) {
    & $pythonPath (Join-Path $projectRoot 'ribao.py') --help
    if ($LASTEXITCODE -ne 0) { throw 'Python entry point check failed.' }
    Write-Output 'Setup launcher check passed; no credentials read, API calls or messages sent.'
    return
}
& $pythonPath (Join-Path $projectRoot 'ribao.py') configure
if ($LASTEXITCODE -ne 0) { throw 'Configuration failed.' }
& $pythonPath (Join-Path $projectRoot 'ribao.py') doctor
if ($LASTEXITCODE -ne 0) { throw 'Configuration check failed.' }
& $pythonPath (Join-Path $projectRoot 'ribao.py') run --preview-only
if ($LASTEXITCODE -ne 0) { throw 'Bailian preview was incomplete. Check data before enabling the daily task.' }
& $pythonPath (Join-Path $projectRoot 'ribao.py') test-send
if ($LASTEXITCODE -ne 0) { throw 'Feishu test failed.' }
& $pythonPath (Join-Path $projectRoot 'ribao.py') run
if ($LASTEXITCODE -ne 0) { throw 'Daily report delivery was incomplete.' }
& (Join-Path $PSScriptRoot 'install-task.ps1')
