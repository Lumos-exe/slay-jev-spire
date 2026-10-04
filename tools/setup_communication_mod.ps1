param(
    [string]$ConfigPath = "$env:LOCALAPPDATA\ModTheSpire\CommunicationMod\config.properties",
    [switch]$ExecuteOnce,
    [switch]$Combat,
    [switch]$Run,
    [switch]$StartNew,
    [ValidateRange(0,2000)][int]$MaxDecisions = 0,
    [ValidateSet('mock', 'jev')][string]$Mode = 'mock'
)

$ErrorActionPreference = 'Stop'
if (([int]$ExecuteOnce.IsPresent + [int]$Combat.IsPresent + [int]$Run.IsPresent) -gt 1) { throw 'Choose only one of ExecuteOnce, Combat, or Run.' }
if ($StartNew -and !$Run) { throw 'StartNew requires Run.' }
if ($MaxDecisions -eq 0) { if ($Run) { $MaxDecisions = 500 } else { $MaxDecisions = 20 } }
if (!$Run -and $MaxDecisions -gt 50) { throw 'Combat request budget must be 1-50.' }
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$entryPath = Join-Path $projectRoot 'capture_game.py'
if (!(Test-Path -LiteralPath $pythonPath) -or !(Test-Path -LiteralPath $entryPath)) {
    throw 'Python environment or capture entry is missing.'
}
if ($pythonPath -match '\s' -or $entryPath -match '\s') {
    throw 'CommunicationMod splits arguments on whitespace; move the project to a path without spaces.'
}
if (!(Test-Path -LiteralPath $ConfigPath)) {
    throw 'Run the game once with CommunicationMod enabled to create its config.'
}

$backupDirectory = Join-Path $projectRoot 'logs\config-backups'
New-Item -ItemType Directory -Force -Path $backupDirectory | Out-Null
$backupPath = Join-Path $backupDirectory ('communicationmod-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.properties')
Copy-Item -LiteralPath $ConfigPath -Destination $backupPath
$command = "$pythonPath -X utf8 -u $entryPath --input-encoding gbk"
if ($ExecuteOnce) {
    $command += " --execute-once $Mode"
}
if ($Run) { $command += " --run $Mode --max-decisions $MaxDecisions" }
if ($StartNew) { $command += ' --start-new' }
if ($Combat) { $command += " --combat $Mode --max-decisions $MaxDecisions" }
# Escape Java Properties syntax; quotes would become literal command characters.
$escapedCommand = $command.Replace('\', '\\').Replace(':', '\:')
$remaining = @(Get-Content -LiteralPath $ConfigPath | Where-Object {
    $_ -notmatch '^\s*(command|runAtGameStart)\s*[:=]'
})
$updated = $remaining + @("command=$escapedCommand", 'runAtGameStart=true')
[System.IO.File]::WriteAllLines($ConfigPath, $updated, [System.Text.UTF8Encoding]::new($false))
Write-Output "Configured: $ConfigPath"
Write-Output "Backup: $backupPath"
Write-Output "Command: $command"
