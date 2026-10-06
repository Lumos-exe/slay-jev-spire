param([switch]$CombatOnly, [switch]$ExistingMenu, [ValidateRange(1,2000)][int]$MaxDecisions=500)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$latest=Join-Path $root 'logs\live\latest_state.json'
$oldEpoch=$null
if (Test-Path $latest) { $oldEpoch=(Get-Content $latest -Raw -Encoding UTF8 | ConvertFrom-Json).jev_protocol.epoch }
$build=Join-Path $root 'build\saved-run-recovery'
New-Item -ItemType Directory -Force -Path $build | Out-Null
& javac --release 8 -d $build (Join-Path $PSScriptRoot 'native-recovery\ContinueSavedRunAgentV2.java')
if ($LASTEXITCODE -ne 0) { throw 'Continue agent compile failed' }
& javac --add-modules jdk.attach -d $build (Join-Path $PSScriptRoot 'native-recovery\AttachController.java')
if ($LASTEXITCODE -ne 0) { throw 'Attach launcher compile failed' }
$agent=Join-Path $build ('continue-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')+'.jar')
& jar cfm $agent (Join-Path $PSScriptRoot 'native-recovery\continue-manifest.mf') -C $build ContinueSavedRunAgentV2.class
if ($LASTEXITCODE -ne 0) { throw 'Continue agent packaging failed' }
if (!$ExistingMenu) {
    & (Join-Path $PSScriptRoot 'launch_jev.ps1') -CombatOnly:$CombatOnly -MaxDecisions $MaxDecisions
    if ($LASTEXITCODE -ne 0) { throw 'Game launch failed' }
}
$deadline=(Get-Date).AddSeconds(60)
$ready=$false
do {
    Start-Sleep -Milliseconds 500
    if (!(Test-Path $latest)) { continue }
    $raw=Get-Content $latest -Raw -Encoding UTF8 | ConvertFrom-Json
    $ready=($raw.in_game -eq $false -and ($ExistingMenu -or $raw.jev_protocol.epoch -ne $oldEpoch) -and $raw.available_commands -contains 'start')
    if ($ready) { break }
} while ((Get-Date) -lt $deadline)
if (!$ready) { throw 'New game did not reach its main menu.' }
$games=@(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('java.exe','javaw.exe') -and $_.CommandLine -match 'ModTheSpire.jar' })
if ($games.Count -ne 1) { throw 'Expected exactly one game.' }
$report=Join-Path $root ('logs\live-debug\continue-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')+'.log')
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $report) | Out-Null
$java=Join-Path (Split-Path -Parent (Get-Command javac).Source) 'java.exe'
& $java --add-modules jdk.attach -cp $build AttachController $games[0].ProcessId $agent $report
if ($LASTEXITCODE -ne 0) { throw 'Continue agent attach failed' }
Write-Output "Continue requested; verify $report and the loaded RunId."
