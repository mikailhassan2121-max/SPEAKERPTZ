@echo off
cd /d "%~dp0"
echo Running the automated rehearsal scenario suite (no hardware required).
.venv\Scripts\python.exe -m speakerptz.main --config config\local.yaml --rehearsal-check
pause
