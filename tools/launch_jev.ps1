param(
    [string]$GameDirectory = 'C:\Program Files (x86)\Steam\steamapps\common\SlayTheSpire',
    [string]$WorkshopDirectory = 'C:\Program Files (x86)\Steam\steamapps\workshop\content\646570',
    [ValidateRange(1,2000)][int]$MaxDecisions = 500,
    [ValidateSet('jev','external')][string]$DecisionMode = 'jev',
    [switch]$StartNew,
    [switch]$CombatOnly,
    [string]$Seed,
    [ValidateRange(1,128)][int]$BeamWidth = 32,
    [ValidateSet('none','drop_settled','duplicate_action')][string]$FaultInjection = 'none',
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'

function Set-CommunicationCommand {
param(
    [string]$ConfigPath = "$env:LOCALAPPDATA\ModTheSpire\CommunicationMod\config.properties",
    [switch]$ExecuteOnce,
    [switch]$Combat,
    [switch]$Run,
    [switch]$StartNew,
    [string]$Seed,
    [ValidateRange(1,128)][int]$BeamWidth = 32,
    [ValidateSet('none','drop_settled','duplicate_action')][string]$FaultInjection = 'none',
    [ValidateRange(0,2000)][int]$MaxDecisions = 0,
    [ValidateSet('mock', 'jev', 'external')][string]$Mode = 'mock'
)

$ErrorActionPreference = 'Stop'
if (([int]$ExecuteOnce.IsPresent + [int]$Combat.IsPresent + [int]$Run.IsPresent) -gt 1) { throw 'Choose only one of ExecuteOnce, Combat, or Run.' }
if ($StartNew -and !$Run -and !$Combat) { throw 'StartNew requires Run or Combat.' }
if ($MaxDecisions -eq 0) { if ($Run) { $MaxDecisions = 500 } else { $MaxDecisions = 20 } }
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
if ($FaultInjection -ne 'none') { $command += " --fault-injection $FaultInjection" }
if ($ExecuteOnce) {
    $command += " --execute-once $Mode"
}
if ($Run) { $command += " --run $Mode --max-decisions $MaxDecisions" }
if ($StartNew) { $command += ' --start-new' }
if ($Seed) {
    if ($Seed -notmatch '^[A-Za-z0-9]+$') { throw 'Invalid seed.' }
    $command += " --seed $Seed"
}
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

}
$projectRoot = Split-Path -Parent $PSScriptRoot
$javaPath = Join-Path $GameDirectory 'jre\bin\java.exe'
$loaderPath = Join-Path $WorkshopDirectory '1605060445\ModTheSpire.jar'
$stateModPath = Join-Path $projectRoot 'build\jev-state\JevState.jar'
$requiredPaths = @(
    $javaPath, $loaderPath,
    (Join-Path $GameDirectory 'desktop-1.0.jar'),
    (Join-Path $WorkshopDirectory '1605833019\BaseMod.jar'),
    (Join-Path $WorkshopDirectory '2131373661\CommunicationMod.jar'),
    (Join-Path $projectRoot '.venv\Scripts\python.exe'), $stateModPath
)
foreach ($requiredPath in $requiredPaths) {
    if (!(Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Missing required file: $requiredPath"
    }
}
$catalogPath = Join-Path $projectRoot 'data\native-catalog.json'
$javaArguments = @(('-Djev.catalog.path="' + $catalogPath + '"'), '-jar', ('"' + $loaderPath + '"'), '--mods', 'basemod,CommunicationMod,jevstate', '--skip-intro')
if ($CheckOnly) {
    Write-Output "Ready: $javaPath $($javaArguments -join ' ')"
    Write-Output "Jev decision budget: $MaxDecisions. No files changed or processes launched."
    return
}

# Inspect only game-relevant Java processes; never terminate an existing game.
$possibleGames = @(Get-CimInstance Win32_Process -Filter "Name='java.exe' OR Name='javaw.exe' OR Name='SlayTheSpire.exe'")
$runningGames = @($possibleGames | Where-Object {
    $_.Name -eq 'SlayTheSpire.exe' -or
    ($_.CommandLine -and ($_.CommandLine.Contains($loaderPath) -or $_.CommandLine.Contains($GameDirectory)))
})
if ($runningGames.Count -gt 0) {
    Write-Output 'Slay the Spire is already running. Exit it normally, then double-click main.py play.'
    Write-Output 'No configuration changed. No second game launched.'
    exit 2
}
if (!(Get-Process -Name steam -ErrorAction SilentlyContinue)) {
    throw 'Start Steam and sign in before launching the game.'
}
if ($DecisionMode -eq 'jev' -and !(Test-Path -LiteralPath (Join-Path $projectRoot 'config\jev-key.dpapi')) -and !$env:TYPESAFE_API_KEY) {
    throw 'Jev key is missing. Run main.py configure first.'
}
$localMods = Join-Path $GameDirectory 'mods'
New-Item -ItemType Directory -Force -Path $localMods | Out-Null
$installedStateMod = Join-Path $localMods 'JevState.jar'
if (!(Test-Path -LiteralPath $installedStateMod) -or
    (Get-FileHash -LiteralPath $installedStateMod).Hash -ne (Get-FileHash -LiteralPath $stateModPath).Hash) {
    if (Test-Path -LiteralPath $installedStateMod) {
        $modBackup = Join-Path $projectRoot 'logs\mod-backups'
        New-Item -ItemType Directory -Force -Path $modBackup | Out-Null
        Copy-Item -LiteralPath $installedStateMod -Destination (Join-Path $modBackup ('JevState-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.jar'))
    }
    Copy-Item -LiteralPath $stateModPath -Destination $installedStateMod
}
Set-CommunicationCommand -Run:(!$CombatOnly) -Combat:$CombatOnly -Mode $DecisionMode -MaxDecisions $MaxDecisions -StartNew:$StartNew -Seed $Seed -BeamWidth $BeamWidth -FaultInjection $FaultInjection
$pausePath = Join-Path $projectRoot 'logs\live\pause.flag'
if (Test-Path -LiteralPath $pausePath) { Remove-Item -LiteralPath $pausePath }
$resumePath = Join-Path $projectRoot 'logs\live\resume.flag'
if (Test-Path -LiteralPath $resumePath) { Remove-Item -LiteralPath $resumePath }
$launchLogs = Join-Path $projectRoot 'logs\launch'
New-Item -ItemType Directory -Force -Path $launchLogs | Out-Null
$launchStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$gameProcess = Start-Process -FilePath $javaPath -ArgumentList $javaArguments -WorkingDirectory $GameDirectory `
    -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $launchLogs "$launchStamp.stdout.log") `
    -RedirectStandardError (Join-Path $launchLogs "$launchStamp.stderr.log")
Write-Output "Game process launched: $($gameProcess.Id). Startup success is not yet confirmed."
if ($StartNew) { Write-Output 'Explicit new-run mode: the agent starts Ironclad A0 at the main menu.' }
else { Write-Output 'At the main menu, choose Continue. Jev takes over supported in-game screens.' }
Write-Output 'Use main.py status to inspect state; main.py pause to pause.'
