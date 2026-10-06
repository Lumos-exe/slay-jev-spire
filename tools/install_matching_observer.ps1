param([Parameter(Mandatory=$true)][int]$GameProcessId)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$process=Get-CimInstance Win32_Process -Filter "ProcessId=$GameProcessId"
if (!$process -or $process.Name -notin @('java.exe','javaw.exe') -or $process.CommandLine -notmatch 'ModTheSpire') { throw 'Not the game process.' }
$build=Join-Path $root ('build\matching-observer\'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Force $build | Out-Null
$game='C:\Program Files (x86)\Steam\steamapps\common\SlayTheSpire\desktop-1.0.jar'
$workshop='C:\Program Files (x86)\Steam\steamapps\workshop\content\646570'
$classpath=$game+';'+$workshop+'\1605833019\BaseMod.jar;'+$workshop+'\2131373661\CommunicationMod.jar;'+$workshop+'\1605060445\ModTheSpire.jar;'+$root+'\build\jev-state\JevState.jar'
& javac --release 8 -classpath $classpath -d $build `
    ($root+'\mods\jev-state\src\jevstate\MatchingGameObservation.java') `
    ($root+'\mods\jev-state\src\jevstate\VisibleCardSlot.java') `
    ($PSScriptRoot+'\native-recovery\InstallMatchingObserverAgentV1.java')
if ($LASTEXITCODE -ne 0) { throw 'Observer compile failed' }
$jar=Join-Path $build 'matching-observer.jar'
& jar cfm $jar ($PSScriptRoot+'\native-recovery\matching-observer-manifest.mf') -C $build .
if ($LASTEXITCODE -ne 0) { throw 'Observer archive failed' }
& javac --add-modules jdk.attach -d $build ($PSScriptRoot+'\native-recovery\AttachController.java')
if ($LASTEXITCODE -ne 0) { throw 'Attach tool compile failed' }
$output=$root+'\logs\live\native-event-observation.json'
$java=Join-Path (Split-Path -Parent (Get-Command javac).Source) 'java.exe'
& $java --add-modules jdk.attach -cp $build AttachController $GameProcessId $jar $output
if ($LASTEXITCODE -ne 0) { throw 'Observer attach failed' }
Write-Output "Observer queued; verify $output before restarting the controller."
