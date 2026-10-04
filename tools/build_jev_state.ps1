param(
    [string]$GameDirectory = 'C:\Program Files (x86)\Steam\steamapps\common\SlayTheSpire',
    [string]$WorkshopDirectory = 'C:\Program Files (x86)\Steam\steamapps\workshop\content\646570',
    [switch]$Install
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $projectRoot 'mods\jev-state'
$buildRoot = Join-Path $projectRoot 'build\jev-state'
$classes = Join-Path $buildRoot 'classes'
$outputJar = Join-Path $buildRoot 'JevState.jar'
$gameJar = Join-Path $GameDirectory 'desktop-1.0.jar'
$loaderJar = Join-Path $WorkshopDirectory '1605060445\ModTheSpire.jar'
$compiler = Get-Command javac -ErrorAction Stop
$archiver = Get-Command jar -ErrorAction Stop
New-Item -ItemType Directory -Force -Path $classes | Out-Null
& $compiler.Source --release 8 -classpath "$gameJar;$loaderJar" -d $classes (Join-Path $sourceRoot 'src\jevstate\CardValues.java')
if ($LASTEXITCODE -ne 0) { throw 'Native state mod compilation failed.' }
Copy-Item -LiteralPath (Join-Path $sourceRoot 'ModTheSpire.json') -Destination (Join-Path $classes 'ModTheSpire.json')
$packageFiles = @('ModTheSpire.json', 'jevstate/CardValues.class', 'jevstate/CardValues$Powers.class', 'jevstate/CardValues$Relics.class', 'jevstate/CardValues$Potions.class', 'jevstate/CardValues$Counters.class', 'jevstate/CardValues$BenchmarkSetup.class', 'jevstate/CardValues$BenchmarkNeow.class', 'jevstate/CardValues$GridSelection.class', 'jevstate/CardValues$TutorialAcknowledgement.class', 'jevstate/CardValues$AutomationState.class')
$packageArguments = @('cf', $outputJar)
foreach ($packageFile in $packageFiles) {
    $packageArguments += @('-C', $classes, $packageFile)
}
& $archiver.Source @packageArguments
if ($LASTEXITCODE -ne 0) { throw 'Native state mod packaging failed.' }
if ($Install) {
    $modDirectory = Join-Path $GameDirectory 'mods'
    New-Item -ItemType Directory -Force -Path $modDirectory | Out-Null
    $destination = Join-Path $modDirectory 'JevState.jar'
    if (Test-Path -LiteralPath $destination) {
        $backupRoot = Join-Path $projectRoot 'logs\mod-backups'
        New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
        Copy-Item -LiteralPath $destination -Destination (Join-Path $backupRoot ('JevState-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.jar'))
    }
    Copy-Item -LiteralPath $outputJar -Destination $destination
    Write-Output "Installed: $destination"
}
Write-Output "Built: $outputJar"
