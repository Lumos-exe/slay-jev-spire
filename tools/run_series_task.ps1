param([string]$SeedList='953716482,953716483,953716484',[string]$SeriesName='20261005-transactions',
      [ValidateRange(1,1440)][int]$MinutesPerRun=30)
$ErrorActionPreference='Stop'
if ($SeriesName -notmatch '^[A-Za-z0-9-]+$') { throw 'Invalid series name.' }
$root=Split-Path -Parent $PSScriptRoot
Set-Location $root
$output=Join-Path $root ('logs\series\'+$SeriesName)
$seeds=$SeedList.Split(',')
New-Item -ItemType Directory -Force $output | Out-Null
# PowerShell 5 treats redirected stderr as NativeCommandError. With Stop it
# truncates Python tracebacks at the first line and can leave driver.log empty.
$arguments = '-X utf8 -u "' + (Join-Path $PSScriptRoot 'play_series.py') + '" --seeds ' +
    ($seeds -join ' ') + ' --directory "' + $output + '" --minutes-per-run ' + $MinutesPerRun
$driver = Start-Process -FilePath (Join-Path $root '.venv\Scripts\python.exe') `
    -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $output 'driver.log') `
    -RedirectStandardError (Join-Path $output 'driver-error.log')
# -Wait waits for the entire process tree, including a game deliberately kept
# open after a technical stop. Only the driver owns the series exit status.
$driver.WaitForExit()
exit $driver.ExitCode
