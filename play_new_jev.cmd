@echo off
cd /d "%~dp0"
echo Starting a NEW Ironclad A0 run. Use play_jev.cmd to continue the existing save instead.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\launch_jev.ps1" -StartNew
if errorlevel 1 echo Launch did not complete. See the message above.
pause
