param(
    [string]$GameDirectory = 'C:\Program Files (x86)\Steam\steamapps\common\SlayTheSpire',
    [string]$WorkshopDirectory = 'C:\Program Files (x86)\Steam\steamapps\workshop\content\646570',
    [switch]$Install
)
$ErrorActionPreference = 'Stop'
if ($Install) {
    $running = @(Get-CimInstance Win32_Process -Filter "Name='java.exe' OR Name='javaw.exe' OR Name='SlayTheSpire.exe'" |
        Where-Object { $_.Name -eq 'SlayTheSpire.exe' -or !$_.CommandLine -or
            $_.CommandLine -match 'ModTheSpire.jar' -or $_.CommandLine.Contains($GameDirectory) })
    if ($running.Count -gt 0) { throw 'Cannot replace a native game JAR while the game is running. Build without -Install, then install after a normal exit.' }
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $projectRoot 'mods\jev-state'
$buildRoot = Join-Path $projectRoot 'build\jev-state'
$classes = Join-Path $buildRoot 'classes'
$outputJar = Join-Path $buildRoot 'JevState.jar'
$gameJar = Join-Path $GameDirectory 'desktop-1.0.jar'
$loaderJar = Join-Path $WorkshopDirectory '1605060445\ModTheSpire.jar'
$communicationJar = Join-Path $WorkshopDirectory '2131373661\CommunicationMod.jar'
$baseModJar = Join-Path $WorkshopDirectory '1605833019\BaseMod.jar'
$compiler = Get-Command javac -ErrorAction Stop
$archiver = Get-Command jar -ErrorAction Stop
if (Test-Path $classes) { Remove-Item -LiteralPath $classes -Recurse -Force }
New-Item -ItemType Directory -Force -Path $classes | Out-Null
$sources = @(Get-ChildItem (Join-Path $sourceRoot 'src\jevstate') -Filter '*.java' | Select-Object -ExpandProperty FullName)
& $compiler.Source --release 8 -classpath "$gameJar;$loaderJar;$communicationJar;$baseModJar" -d $classes @sources
if ($LASTEXITCODE -ne 0) { throw 'Native state mod compilation failed.' }
Copy-Item -LiteralPath (Join-Path $sourceRoot 'ModTheSpire.json') -Destination (Join-Path $classes 'ModTheSpire.json')
& $archiver.Source cf $outputJar -C $classes .
if ($LASTEXITCODE -ne 0) { throw 'Native state mod packaging failed.' }
if ($Install) {
    $modDirectory = Join-Path $GameDirectory 'mods'
    New-Item -ItemType Directory -Force -Path $modDirectory | Out-Null
    $destination = Join-Path $modDirectory 'JevState.jar'
    if (Test-Path -LiteralPath $destination) {
        $backupRoot = Join-Path $projectRoot 'logs\mod-backups'
        New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
        $backupPath = Join-Path $backupRoot ('JevState-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.jar')
    }
    $staged = $destination + '.next'
    Copy-Item -LiteralPath $outputJar -Destination $staged
    if (Test-Path -LiteralPath $destination) {
        [System.IO.File]::Replace($staged, $destination, $backupPath)
    } else {
        [System.IO.File]::Move($staged, $destination)
    }
    Write-Output "Installed: $destination"
}
Write-Output "Built: $outputJar"
