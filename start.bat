@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title EKO Revenue Reconciliation - Launcher

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "VENV_HOME=%LOCALAPPDATA%\EkoSBI\venv_v62_6_115"
set "PY=%VENV_HOME%\Scripts\python.exe"

REM ---- Find Python ----
set "PYBASE="
where python >nul 2>&1
if not errorlevel 1 set "PYBASE=python"
if not defined PYBASE (
  where py >nul 2>&1
  if not errorlevel 1 set "PYBASE=py -3"
)
if not defined PYBASE (
  echo ERROR: Python was not found. Install Python 3.10+ and enable PATH.
  pause
  exit /b 1
)

REM ---- Create virtual environment and install backend dependencies ----
if not exist "%PY%" (
  echo [1/6] Creating backend environment...
  if not exist "%LOCALAPPDATA%\EkoSBI" mkdir "%LOCALAPPDATA%\EkoSBI"
  %PYBASE% -m venv "%VENV_HOME%"
  if errorlevel 1 (
    echo ERROR: Python virtual environment creation failed at "%VENV_HOME%".
    pause
    exit /b 1
  )
)
"%PY%" -c "import fastapi,uvicorn,pandas,openpyxl,python_calamine,pgserver,cryptography,multipart,pydantic,dotenv,itsdangerous,sqlalchemy,alembic,psycopg,authlib,httpx" >nul 2>&1
if errorlevel 1 (
  echo [2/6] Installing backend packages...
  cd /d "%BACKEND%"
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo ERROR: Backend package installation failed. See the error above.
    pause
    exit /b 1
  )
)

REM ---- HTTPS (EKO_HTTPS=true in backend\.env): same launcher, https URLs, certificate created if missing ----
set "SCHEME=http"
REM The extra outer quotes below are required: without them, cmd.exe mis-parses this command when
REM the Python path contains a space (e.g. a Windows user name with a space, "C:\Users\Jane Doe\...").
for /f "usebackq delims=" %%S in (`""%PY%" "%BACKEND%\env_flag.py" EKO_HTTPS"`) do if /i "%%S"=="true" set "SCHEME=https"
if /i "%SCHEME%"=="https" "%PY%" "%BACKEND%\make_local_cert.py"
set "API=%SCHEME%://127.0.0.1:8000"
set "WEB=%SCHEME%://127.0.0.1:5173"

REM ---- Check the backend BEFORE resetting any current workspace data ----
REM Re-running start.bat while this project's backend is healthy must not delete
REM uploads underneath the running process. Reset only when launching a new backend.
cd /d "%ROOT%"
echo [3/6] Checking backend service before workspace initialization...
curl.exe -k -fsS --max-time 2 %API%/health >nul 2>&1
if not errorlevel 1 (
  curl.exe -k -fsS --max-time 2 %API%/api/version | findstr /C:"62.6.216-ui-security-speed" >nul 2>&1
  if not errorlevel 1 (
    echo Existing Revenue Reconciliation backend matches V62.6.216; preserving current uploads and reusing it.
    goto BACKEND_READY
  )
  echo ERROR: Port 8000 is serving a different Revenue Reconciliation version.
  echo Close the old EKO Backend window, then run start.bat again. Current workspace data has NOT been reset.
  pause
  exit /b 1
)
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo ERROR: Port 8000 is already occupied by another or unhealthy process.
  echo Current workspace data has NOT been reset. Run diagnostics_backend.bat and inspect backend_runtime.log.
  pause
  exit /b 1
)

REM ---- Initialize clean current-period state only for a new backend process ----
cd /d "%BACKEND%"
"%PY%" reset_initial_data.py
if errorlevel 1 (
  echo ERROR: Could not initialize clean upload state.
  pause
  exit /b 1
)
REM ---- Settings file: created from the template on first run, never overwritten ----
if not exist "%BACKEND%\.env" if exist "%BACKEND%\.env.example" (
  copy /y "%BACKEND%\.env.example" "%BACKEND%\.env" >nul
  echo Created backend\.env from the template.
)
REM ---- First run: create the first administrator (sign-in is by password) ----
"%PY%" create_platform_admin.py --if-none
if errorlevel 1 (
  echo ERROR: The first administrator account was not created. Run start.bat again.
  pause
  exit /b 1
)
"%PY%" -c "from app.main import app; print('Backend imports OK:', app.title)"
if errorlevel 1 (
  echo ERROR: Backend cannot import. See the Python traceback above.
  pause
  exit /b 1
)
cd /d "%ROOT%"

REM ---- START BACKEND BEFORE FRONTEND INSTALL/BUILD ----
REM This prevents npm install/build failures from leaving an open UI with no API.
echo Starting backend on %API%...
REM serve.py restarts the backend automatically if it ever stops, and logs to backend_runtime.log
start "EKO Backend" /D "%BACKEND%" "%PY%" serve.py

echo Waiting for backend health endpoint...
set /a BCOUNT=0
:WAIT_BACKEND
set /a BCOUNT+=1
curl.exe -k -fsS --max-time 1 %API%/health >nul 2>&1
if not errorlevel 1 goto BACKEND_READY
if %BCOUNT% GEQ 90 goto BACKEND_FAILED
timeout /t 1 /nobreak >nul
goto WAIT_BACKEND

:BACKEND_READY
echo Backend is healthy.

REM ---- Frontend setup only after backend is healthy ----
where npm >nul 2>&1
if errorlevel 1 (
  echo ERROR: Node.js/npm was not found. Backend is healthy, but the UI cannot start.
  pause
  exit /b 1
)
if not exist "%FRONTEND%\node_modules\vite\bin\vite.js" (
  echo [4/6] Installing frontend packages. Backend remains running during this step...
  cd /d "%FRONTEND%"
  call npm.cmd config set registry https://registry.npmjs.org/
  call npm.cmd install --no-audit --no-fund --fetch-retries=5 --fetch-retry-mintimeout=10000 --fetch-retry-maxtimeout=60000 --fetch-timeout=120000
  if errorlevel 1 (
    echo ERROR: Frontend package installation failed. Backend is running and healthy.
    echo Check internet access/VPN/proxy and run verify_frontend.bat.
    pause
    exit /b 1
  )
)

echo [5/6] Verifying frontend production build...
cd /d "%FRONTEND%"
call npm.cmd run build
if errorlevel 1 (
  echo ERROR: Frontend production build failed. Backend is still running and healthy.
  echo Review the Vite error above or run verify_frontend.bat.
  pause
  exit /b 1
)
if not exist "%FRONTEND%\dist\index.html" (
  echo ERROR: Vite returned success but frontend\dist\index.html is missing. Backend is still running.
  pause
  exit /b 1
)
if exist "%FRONTEND%\node_modules\.vite" rmdir /s /q "%FRONTEND%\node_modules\.vite"

REM ---- Start frontend and verify both services ----
echo [6/6] Starting frontend...
curl.exe -k -fsS --max-time 2 %WEB%/ >nul 2>&1
if errorlevel 1 start "EKO Frontend" "%ROOT%run_frontend.bat"
set /a FCOUNT=0
:WAIT_FRONTEND
set /a FCOUNT+=1
curl.exe -k -fsS --max-time 1 %API%/health >nul 2>&1
if errorlevel 1 goto BACKEND_DROPPED
curl.exe -k -fsS --max-time 1 %WEB%/ >nul 2>&1
if not errorlevel 1 goto READY
if %FCOUNT% GEQ 90 goto FRONTEND_FAILED
timeout /t 1 /nobreak >nul
goto WAIT_FRONTEND

:READY
echo.
echo ==============================================
echo   EKO Revenue Reconciliation is READY
echo   Dashboard : %WEB%
echo   Backend   : %API%
echo   Swagger   : %API%/docs
echo ==============================================
echo.
start "" "%WEB%"
echo Browser opened. Keep the service windows running.
exit /b 0

:BACKEND_FAILED
echo ERROR: Backend did not become healthy within 90 seconds.
echo Check the EKO Backend console for Python/Uvicorn errors.
echo Then run diagnostics_backend.bat and inspect backend_diagnostics.log and backend_runtime.log.
pause
exit /b 1

:BACKEND_DROPPED
echo ERROR: Backend stopped responding while starting the frontend.
echo Inspect backend_runtime.log and run diagnostics_backend.bat.
pause
exit /b 1

:FRONTEND_FAILED
echo ERROR: Frontend did not become ready within 90 seconds. Backend remains running.
echo Inspect the EKO Frontend window and run verify_frontend.bat.
pause
exit /b 1
