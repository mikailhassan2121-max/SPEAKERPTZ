@echo off
setlocal
cd /d "%~dp0"
echo ==============================================
echo SPEAKERPTZ v0.9 - School computer setup
echo ==============================================
py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python 3.12 was not found.
  exit /b 1
)
if not exist .venv (
  echo Creating Python environment...
  py -3.12 -m venv .venv
  if errorlevel 1 exit /b 1
)
echo Installing/updating dependencies...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
if not exist config\local.yaml (
  copy /Y config\local.example.yaml config\local.yaml >nul
  echo Created config\local.yaml from the example.
  echo IMPORTANT: edit config\local.yaml for the school audio device and seat map.
) else (
  echo Existing config\local.yaml preserved.
)
if not exist logs mkdir logs
echo.
echo Setup complete.
echo Next: run doctor_school.bat
echo After doctor passes: identify_dante_channels.bat
echo Optional after validation: install_windows_autostart.ps1
