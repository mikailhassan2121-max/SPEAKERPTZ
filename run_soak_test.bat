@echo off
setlocal
cd /d "%~dp0"
.venv\Scripts\python.exe -m speakerptz.main --soak-test --soak-iterations 25000
set EXIT_CODE=%errorlevel%
pause
exit /b %EXIT_CODE%
