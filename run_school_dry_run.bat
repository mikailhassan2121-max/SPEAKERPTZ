@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m speakerptz.main --config config\local.yaml
pause
