@echo off
setlocal
title SimRELAY export
rem SimRELAY: pack the campaign results into .zip files in the sync folder, ready for Google Drive.
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
echo SimRELAY export of the campaign results
echo.
echo   view package : everything the app and the report need, about 3.6 GB
echo   raw package  : raw Simulink output and models, about 9.5 GB (only to relabel or open in Simulink)
echo.
choice /c NY /n /m "Also make the raw package? [N/Y] "
if errorlevel 2 (
  "%PY%" -u sync.py export --raw
) else (
  "%PY%" -u sync.py export
)
echo.
if exist "%~dp0sync" explorer "%~dp0sync"
pause
