@echo off
cd /d "%~dp0"
echo Probing exactly Camera 1 from config\local.yaml. No subnet scan will run.
.venv\Scripts\python.exe -m speakerptz.main --config config\local.yaml --camera-probe 1
pause
