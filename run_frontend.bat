@echo off
setlocal
cd /d "%~dp0frontend"
if not exist "node_modules\vite\bin\vite.js" (
  echo Frontend dependencies are missing. Run start.bat first.
  pause
  exit /b 1
)
echo Starting frontend on port 5173 (https when EKO_HTTPS=true in backend\.env)
call npm.cmd run dev -- --host 127.0.0.1 --port 5173
if errorlevel 1 (
  echo Frontend stopped with an error. Check the output above.
  pause
)
