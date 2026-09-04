@echo off
cd /d "%~dp0"
REM Home test defaults from the current development laptop: device 1, 4 channels.
REM Edit these two values for another machine.
set DEVICE=1
set CHANNELS=4
.venv\Scripts\python.exe -m speakerptz.main --config config\room.yaml --device %DEVICE% --channels %CHANNELS%
pause
