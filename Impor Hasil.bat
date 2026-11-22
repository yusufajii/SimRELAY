@echo off
setlocal
title SimRELAY import
rem SimRELAY: load campaign results exported on another computer.
rem   Double-click: takes the newest SimRELAY_*.zip in the Downloads folder or the sync folder.
rem   Or drag one or more SimRELAY_*.zip files onto this file.
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
echo SimRELAY import of campaign results
echo.
"%PY%" -u sync.py import %*
echo.
echo When the import is done, open or refresh the app: the campaign appears by itself.
pause
