@echo off
setlocal
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
echo.
echo SPEAKERPTZ setup complete.
echo Run run_simulation.bat or list_audio_devices.bat next.
