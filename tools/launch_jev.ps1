param(
    [string]$GameDirectory = 'C:\Program Files (x86)\Steam\steamapps\common\SlayTheSpire',
    [string]$WorkshopDirectory = 'C:\Program Files (x86)\Steam\steamapps\workshop\content\646570',
    [ValidateRange(1,2000)][int]$MaxDecisions = 500,
    [switch]$StartNew,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
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
$javaArguments = @('-jar', ('"' + $loaderPath + '"'), '--mods', 'basemod,CommunicationMod,jevstate', '--skip-intro')
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
    Write-Output 'Slay the Spire is already running. Exit it normally, then double-click play_jev.cmd.'
    Write-Output 'No configuration changed. No second game launched.'
    exit 2
}
if (!(Get-Process -Name steam -ErrorAction SilentlyContinue)) {
    throw 'Start Steam and sign in before launching the game.'
}
if (!(Test-Path -LiteralPath (Join-Path $projectRoot 'config\jev-key.dpapi')) -and !$env:TYPESAFE_API_KEY) {
    throw 'Jev key is missing. Run configure_jev.cmd first.'
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
& (Join-Path $PSScriptRoot 'setup_communication_mod.ps1') -Run -Mode jev -MaxDecisions $MaxDecisions -StartNew:$StartNew
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
Write-Output 'Use status_jev.cmd to inspect state; pause_combat.cmd to pause.'
