@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\launch_jev.ps1"
if errorlevel 1 echo Launch did not complete. See the message above.
pause
