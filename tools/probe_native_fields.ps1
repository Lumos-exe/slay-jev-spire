param([Parameter(Mandatory=$true)][int]$GameProcessId)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$process=Get-CimInstance Win32_Process -Filter "ProcessId=$GameProcessId"
if (!$process -or $process.Name -notin @('java.exe','javaw.exe') -or $process.CommandLine -notmatch 'ModTheSpire') {
    throw 'Target is not the verified game process.'
}
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$build=Join-Path $root ('build\native-fields-probe\'+$stamp)
New-Item -ItemType Directory -Force $build | Out-Null
& javac --release 8 -d $build (Join-Path $root 'mods\jev-state\src\jevstate\NativeFields.java') `
    (Join-Path $PSScriptRoot 'native-recovery\ReadNativeFieldsAgentV1.java')
if ($LASTEXITCODE -ne 0) { throw 'Probe compile failed' }
$jar=Join-Path $build 'fields-probe.jar'
& jar cfm $jar (Join-Path $PSScriptRoot 'native-recovery\fields-probe-manifest.mf') -C $build .
if ($LASTEXITCODE -ne 0) { throw 'Probe archive failed' }
& javac --add-modules jdk.attach -d $build (Join-Path $PSScriptRoot 'native-recovery\AttachController.java')
if ($LASTEXITCODE -ne 0) { throw 'Attach tool compile failed' }
$report=Join-Path $root ('logs\native-field-probes\'+$stamp+'.json')
$java=Join-Path (Split-Path -Parent (Get-Command javac).Source) 'java.exe'
& $java --add-modules jdk.attach -cp $build AttachController $GameProcessId $jar $report
if ($LASTEXITCODE -ne 0) { throw 'Read-only probe attach failed' }
Write-Output "Read-only probe queued: $report"
