@echo off
cd /d "%~dp0"
if not exist "%~dp0logs\live" mkdir "%~dp0logs\live"
echo pause>"%~dp0logs\live\pause.flag"
echo 500>"%~dp0logs\live\resume.flag"
echo Resume requested. The updated run process reloads code, refreshes state,
echo and permits up to 500 additional requests. It never resends old commands.
echo Time and action limits remain in force.
echo Requires the version that supports resume; old processes need one restart.
pause
