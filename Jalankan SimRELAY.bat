@echo off
title SimRELAY
rem ---------------------------------------------------------------
rem  SimRELAY: one-click launcher.
rem  Starts the local server (if it is not already running) and
rem  opens the app in Microsoft Edge at http://127.0.0.1:8034
rem  To stop the app, close the "SimRELAY Server" window.
rem ---------------------------------------------------------------
cd /d "%~dp0"
set URL=http://127.0.0.1:8034

rem Prefer the project environment (.venv, Python 3.11 with matlabengine) when it exists:
rem the MATLAB R2024b engine supports Python 3.9 to 3.12 only.
set PY=python
if exist "%~dp0.venv\Scripts\python.exe" set PY="%~dp0.venv\Scripts\python.exe"

%PY% -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(0 if s.connect_ex(('127.0.0.1',8034))==0 else 1)" >nul 2>&1
if %errorlevel%==0 goto open

%PY% --version >nul 2>&1
if errorlevel 1 (
  echo Python was not found. Install Python 3.9+ and numpy, then try again.
  pause
  exit /b 1
)

echo Starting SimRELAY server...
start "SimRELAY Server" /min %PY% server.py --no-browser

rem Wait up to 120 s for the server to accept connections.
set /a tries=0
:wait
%PY% -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(0 if s.connect_ex(('127.0.0.1',8034))==0 else 1)" >nul 2>&1
if %errorlevel%==0 goto open
set /a tries+=1
if %tries% geq 120 (
  echo The server did not start. Check the "SimRELAY Server" window for errors.
  pause
  exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait

:open
start "" msedge "%URL%"
exit /b 0
