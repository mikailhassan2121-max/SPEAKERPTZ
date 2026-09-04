@echo off
cd /d "%~dp0"
echo Manual real-movement test for Camera 1. An exact typed confirmation is required.
.venv\Scripts\python.exe -m speakerptz.main --config config\local.yaml --camera-test 1
pause
