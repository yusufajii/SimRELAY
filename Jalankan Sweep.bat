@echo off
setlocal EnableExtensions
rem ---------------------------------------------------------------------------
rem  SimRELAY: launcher for the MATLAB campaign "Proof of Urgencies" in 5 parts.
rem
rem    Jalankan Sweep.bat 2        run part 2, then parts 3, 4 and 5 one after another
rem    Jalankan Sweep.bat 2 4      the same, starting with 4 workers (default below)
rem    Jalankan Sweep.bat list     show the parts and their progress
rem
rem  Double-click it in Explorer to run without Claude: the sweep then does not depend
rem  on any other program and keeps running when Claude is closed.
rem
rem  The sweep runs from a frozen copy of the code in .sweep\ (made on the first
rem  launch and reused by every part), in its own window, so the app, its code and
rem  Claude can be used and edited meanwhile. Results go to
rem  campaigns\PoU-TA-Proteksi-Adaptif (visible in the app).
rem
rem  Worker fallback: a part runs on WORKERS MATLAB workers. If MATLAB stops with an
rem  error (for example a worker running out of memory), every MATLAB process is
rem  closed and the same part continues on FALLBACK workers, and the remaining parts
rem  keep that number. Each part is resumable, so no finished case is lost.
rem  The runner log is campaigns\PoU-TA-Proteksi-Adaptif\logs\runner.log.
rem  Close the sweep window to stop; launch again with the same part to continue.
rem ---------------------------------------------------------------------------
set "ROOT=%~dp0"
if exist "%~dp0snapshot.json" for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
cd /d "%ROOT%"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "SNAP=%ROOT%.sweep"
set "OUTD=%ROOT%campaigns\PoU-TA-Proteksi-Adaptif"
set "RLOG=%OUTD%\logs\runner.log"
rem MATLAB parallel workers: about 2 GB of RAM each plus 1.5 GB for the main session.
set "WORKERS=4"
set "FALLBACK=3"
set "LASTPART=5"
if not exist "%PY%" (
  echo The project environment .venv was not found.
  pause
  exit /b 1
)
if /i "%~1"=="run" goto :run

if not exist "%SNAP%\batch.py" (
  echo Making the frozen code copy in .sweep ...
  robocopy "%ROOT%engine" "%SNAP%\engine" *.py /E /NFL /NDL /NJH /NJS /NP >nul
  robocopy "%ROOT%matlab" "%SNAP%\matlab" *.m /E /NFL /NDL /NJH /NJS /NP >nul
  robocopy "%ROOT%cache" "%SNAP%\cache" settings.pkl /NFL /NDL /NJH /NJS /NP >nul
  copy /y "%ROOT%batch.py" "%SNAP%\batch.py" >nul
  copy /y "%ROOT%campaign.py" "%SNAP%\campaign.py" >nul
  "%PY%" -c "import subprocess,time,json;r=lambda *a:subprocess.run(['git',*a],capture_output=True,text=True).stdout.strip();json.dump({'made':time.strftime('%%Y-%%m-%%d %%H:%%M:%%S'),'commit':r('rev-parse','HEAD'),'uncommitted':r('status','--short').splitlines()},open(r'%SNAP%\snapshot.json','w'),indent=1)"
)

if /i "%~1"=="list" (
  "%PY%" "%SNAP%\batch.py" --campaign --outdir "%OUTD%" --list-parts
  pause
  exit /b 0
)

call :busy
if errorlevel 1 (
  echo A sweep is already running. Close its window first.
  timeout /t 10 >nul
  exit /b 1
)
set "PART=%~1"
if "%PART%"=="" set /p PART=First part to run (1 to %LASTPART%):
if "%PART%"=="" exit /b 1
set "W=%~2"
if "%W%"=="" set "W=%WORKERS%"
rem The runner is a copy, so editing this file later cannot disturb a running sweep.
copy /y "%~f0" "%SNAP%\runner.bat" >nul
start "SimRELAY Sweep" cmd /k call "%SNAP%\runner.bat" run %PART% %W%
start "SimRELAY Sweep progress" "%PY%" "%ROOT%progress.py" --live
echo Parts %PART% to %LASTPART% started in the window "SimRELAY Sweep" on %W% workers.
echo Live progress opens in "SimRELAY Sweep progress" (also: Pantau Sweep.bat).
timeout /t 5 >nul
exit /b 0

rem ---------------------------------------------------------------------------
:run
set "PART=%~2"
set "W=%~3"
set "TRIES=0"
if not exist "%OUTD%\logs" mkdir "%OUTD%\logs"
call :log "runner started: parts %PART% to %LASTPART%, %W% workers"
:part_loop
if %PART% GTR %LASTPART% goto :all_done
title SimRELAY Sweep part %PART% on %W% workers
call :log "part %PART% starting on %W% workers"
"%PY%" -u "%SNAP%\batch.py" --campaign --part %PART% --workers %W% --outdir "%OUTD%" --log "%OUTD%\logs\part%PART%.log"
if errorlevel 1 goto :failed
call :complete %PART%
if not errorlevel 1 goto :part_ok
set /a TRIES+=1
if %TRIES% GEQ 2 goto :part_partial
call :log "part %PART% has cases that failed on their own in MATLAB; running them once more"
goto :part_loop
:part_partial
call :log "part %PART% still has cases that fail on their own in MATLAB; moving on"
:part_ok
call :log "part %PART% finished"
set /a PART+=1
set "TRIES=0"
goto :part_loop

:failed
call :log "part %PART% stopped with an error on %W% workers"
taskkill /f /im MATLAB.exe >nul 2>&1
timeout /t 20 /nobreak >nul
if %W% GTR %FALLBACK% (
  call :log "closed every MATLAB process; continuing part %PART% on %FALLBACK% workers"
  set "W=%FALLBACK%"
  goto :part_loop
)
set /a TRIES+=1
if %TRIES% LSS 2 (
  call :log "closed every MATLAB process; trying part %PART% once more on %W% workers"
  goto :part_loop
)
call :log "part %PART% failed twice on %W% workers; the runner stops here"
echo.
echo The sweep stopped. Check %OUTD%\logs\part%PART%.log
exit /b 1

:all_done
call :log "all parts up to %LASTPART% are finished"
title SimRELAY Sweep finished
echo.
echo All parts up to %LASTPART% are finished. This window can be closed.
exit /b 0

rem errorlevel 1 when part %1 still has cases without a result
:complete
set "D=" & set "N="
"%PY%" "%SNAP%\batch.py" --campaign --outdir "%OUTD%" --list-parts > "%OUTD%\logs\parts.txt" 2>nul
for /f "tokens=3,4 delims=:/ " %%a in ('findstr /b /c:"part %~1:" "%OUTD%\logs\parts.txt"') do (
  set "D=%%a"
  set "N=%%b"
)
if not defined D exit /b 0
if "%D%"=="%N%" exit /b 0
exit /b 1

rem errorlevel 1 when a campaign sweep (batch.py) is already running
:busy
powershell -NoProfile -Command "if (Get-CimInstance Win32_Process -Filter 'Name=''python.exe''' | Where-Object { $_.CommandLine -match 'batch\.py' -and $_.CommandLine -notmatch 'list-parts' }) { exit 1 } else { exit 0 }"
exit /b %errorlevel%

:log
echo [%date% %time:~0,8%] %~1
>> "%RLOG%" echo [%date% %time:~0,8%] %~1
exit /b 0
