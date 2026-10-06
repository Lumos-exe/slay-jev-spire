param([Parameter(Mandatory=$true)][int]$GameProcessId)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$process=Get-CimInstance Win32_Process -Filter "ProcessId=$GameProcessId"
if (!$process -or $process.Name -notin @('java.exe','javaw.exe') -or $process.CommandLine -notmatch 'ModTheSpire') {
    throw 'Target is not the verified ModTheSpire game process.'
}
$build=Join-Path $root 'build\controller-recovery'
New-Item -ItemType Directory -Force $build | Out-Null
$src=Join-Path $PSScriptRoot 'native-recovery'
& javac --release 8 -d $build (Join-Path $src 'RestartCommunicationAgentV3.java')
if ($LASTEXITCODE -ne 0) { throw 'Agent compile failed' }
& javac --add-modules jdk.attach -d $build (Join-Path $src 'AttachController.java')
if ($LASTEXITCODE -ne 0) { throw 'Attach launcher compile failed' }
$agent=Join-Path $build ('restart-controller-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')+'.jar')
& jar cfm $agent (Join-Path $src 'manifest.mf') -C $build RestartCommunicationAgentV3.class
if ($LASTEXITCODE -ne 0) { throw 'Agent packaging failed' }
$report=Join-Path $root ('logs\live-debug\restart-'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')+'.log')
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $report) | Out-Null
$java=Join-Path (Split-Path -Parent (Get-Command javac).Source) 'java.exe'
& $java --add-modules jdk.attach -cp $build AttachController $GameProcessId $agent $report
if ($LASTEXITCODE -ne 0) { throw 'Controller attach failed' }
$deadline=(Get-Date).AddSeconds(15)
do {
    if (Test-Path $report) {
        $status=Get-Content -Raw $report
        if ($status -match 'controller_restart=true') { Write-Output 'Controller restart confirmed.'; Write-Output $report; return }
        if ($status -match '_failed=|controller_restart=false') { throw "Controller restart failed; see $report" }
    }
    Start-Sleep -Milliseconds 200
} while ((Get-Date) -lt $deadline)
throw "Controller restart not confirmed; see $report"
