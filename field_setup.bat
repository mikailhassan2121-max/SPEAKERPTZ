@echo off
cd /d "%~dp0"
echo ==============================================
echo SPEAKERPTZ v1.0-rc1 - Guided school field setup
echo ==============================================
echo This walks through the recommended installation/calibration order.
echo Real PTZ control is never enabled by this workflow.
echo.
.venv\Scripts\python.exe -m speakerptz.main --config config\local.yaml --field-setup
pause
