@echo off
rem SimRELAY: live progress of the MATLAB campaign, refreshed every 3 s.
rem Only reads the campaign folder; closing this window does not stop the sweep.
cd /d "%~dp0"
start "SimRELAY Sweep progress" "%~dp0.venv\Scripts\python.exe" "%~dp0progress.py" --live
