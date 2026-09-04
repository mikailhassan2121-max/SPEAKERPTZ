@echo off
cd /d "%~dp0"
echo Guided per-mic room calibration. Requires seats to already be mapped and,
echo for a real room, runtime.mode: real in config\local.yaml.
echo Only derived dB values are stored; no audio is recorded.
.venv\Scripts\python.exe -m speakerptz.main --config config\local.yaml --calibrate
pause
