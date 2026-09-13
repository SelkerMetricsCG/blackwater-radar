@echo off
rem Starts the radar capture on this PC in its own (minimized) console window.
rem Runs continuously until you run stop_capture.cmd.
rem NOTE: the capture normally runs on GitHub Actions now; only run this here if that is off.
cd /d "%~dp0"
start "Radar Capture" /min cmd /k python capture.py
echo Radar capture started in a minimized window "Radar Capture".
