@echo off
rem Tells a running capture.py to stop (it checks for this file every ~20 s).
cd /d "%~dp0"
echo stop > STOP
echo Stop requested. The "Radar Capture" window will close itself shortly.
