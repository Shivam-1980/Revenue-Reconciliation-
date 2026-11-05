@echo off
setlocal EnableExtensions
cd /d "%~dp0backend"
set "ROOT=%~dp0"
if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "PY=%LOCALAPPDATA%\EkoSBI\venv_v62_6_115\Scripts\python.exe"
set "LOG=%ROOT%backend_runtime.log"
if not exist "%PY%" (
  echo ERROR: Backend virtual environment is missing.
  echo Run start.bat from the extracted project folder; do not run frontend alone.
  >>"%LOG%" echo [%DATE% %TIME%] ERROR: Backend virtual environment missing: %PY%
  pause
  exit /b 1
)
"%PY%" -c "import fastapi,uvicorn,pandas,openpyxl,multipart,pydantic,dotenv" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Required backend packages are missing in the EkoSBI environment.
  echo Run start.bat to repair/install dependencies.
  >>"%LOG%" echo [%DATE% %TIME%] ERROR: Backend dependency import check failed.
  pause
  exit /b 1
)
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul 2>&1
if not errorlevel 1 (
  curl.exe -fsS --max-time 2 http://127.0.0.1:8000/health >nul 2>&1
  if not errorlevel 1 (
    echo Backend is already healthy at http://127.0.0.1:8000/health
    exit /b 0
  )
  echo ERROR: Port 8000 is occupied by another or unhealthy process.
  echo Close the conflicting process or inspect diagnostics_backend.bat output.
  >>"%LOG%" echo [%DATE% %TIME%] ERROR: Port 8000 occupied but health check failed.
  pause
  exit /b 1
)
echo Starting FastAPI backend on http://127.0.0.1:8000
>>"%LOG%" echo.
>>"%LOG%" echo [%DATE% %TIME%] Starting backend using "%PY%"
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info >>"%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
>>"%LOG%" echo [%DATE% %TIME%] Backend process exited with code %RC%.
echo.
echo Backend process stopped with exit code %RC%.
echo Review backend_runtime.log for the full traceback.
type "%LOG%"
pause
exit /b %RC%
