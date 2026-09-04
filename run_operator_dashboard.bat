@echo off
cd /d "%~dp0"
echo Starting SPEAKERPTZ with the localhost operator dashboard.
echo Open http://127.0.0.1:8765 in this computer's browser.
.venv\Scripts\python.exe -m speakerptz.main --config config\room.yaml --simulate
pause
