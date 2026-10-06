param([Parameter(Mandatory=$true)][int]$GameProcessId)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$process=Get-CimInstance Win32_Process -Filter "ProcessId=$GameProcessId"
if (!$process -or $process.Name -notin @('java.exe','javaw.exe') -or $process.CommandLine -notmatch 'ModTheSpire') {
    throw 'Target is not the verified game process.'
}
$build=Join-Path $root ('build\keyword-probe\'+(Get-Date -Format 'yyyyMMddHHmmssfff'))
New-Item -ItemType Directory -Force $build | Out-Null
& javac --release 8 -d $build (Join-Path $PSScriptRoot 'native-recovery\ReadKeywordRegistryAgentV1.java')
if ($LASTEXITCODE -ne 0) { throw 'Compile failed' }
$agent=Join-Path $build 'keyword-probe.jar'
& jar cfm $agent (Join-Path $PSScriptRoot 'native-recovery\keyword-probe-manifest.mf') -C $build ReadKeywordRegistryAgentV1.class
if ($LASTEXITCODE -ne 0) { throw 'Archive failed' }
& javac --add-modules jdk.attach -d $build (Join-Path $PSScriptRoot 'native-recovery\AttachController.java')
if ($LASTEXITCODE -ne 0) { throw 'Attach helper failed' }
$report=Join-Path $root 'logs\native-keywords.json'
New-Item -ItemType Directory -Force (Split-Path -Parent $report) | Out-Null
$java=Join-Path (Split-Path -Parent (Get-Command javac).Source) 'java.exe'
& $java --add-modules jdk.attach -cp $build AttachController $GameProcessId $agent $report
if ($LASTEXITCODE -ne 0) { throw 'Read-only attach failed' }
Write-Output "Native keyword snapshot queued: $report"
