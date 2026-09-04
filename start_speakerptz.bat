@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe exit /b 10
if not exist config\local.yaml exit /b 11

REM Run the non-moving startup doctor before the long-running controller.
.venv\Scripts\python.exe -m speakerptz.main --config config\local.yaml --doctor
if errorlevel 1 exit /b %errorlevel%

REM In real-camera mode SPEAKERPTZ always starts AUTO OFF, regardless of YAML.
.venv\Scripts\python.exe -m speakerptz.main --config config\local.yaml
exit /b %errorlevel%
