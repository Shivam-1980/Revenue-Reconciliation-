@echo off
setlocal
cd /d "%~dp0"
if not exist "..\venv\Scripts\python.exe" (
  echo Python virtual environment not found at ..\venv. Run the project installer first.
  pause
  exit /b 1
)
"..\venv\Scripts\python.exe" -m app.services.platform_worker
if errorlevel 1 echo Platform worker exited with an error.
pause
