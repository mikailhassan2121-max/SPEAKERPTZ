@echo off
cd /d "%~dp0"
echo Building the SPEAKERPTZ field readiness report.
.venv\Scripts\python.exe -m speakerptz.main --config config\local.yaml --field-readiness
pause
