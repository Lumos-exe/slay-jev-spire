@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" -X utf8 -c "from pathlib import Path; p=Path('logs/live/pause.flag'); p.parent.mkdir(parents=True,exist_ok=True); p.write_text('pause',encoding='utf-8'); print('Automatic combat paused. Current API request may finish; no new action will be sent.')"
pause
