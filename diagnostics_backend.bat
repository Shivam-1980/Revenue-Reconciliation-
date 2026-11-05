@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title EKO Revenue Reconciliation - Backend Diagnostics
set "LOG=%~dp0backend_diagnostics.log"
if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "PY=%LOCALAPPDATA%\EkoSBI\venv_v62_6_115\Scripts\python.exe"
>"%LOG%" echo EKO Revenue Reconciliation Backend Diagnostics
>>"%LOG%" echo Time: %DATE% %TIME%
>>"%LOG%" echo Project: %~dp0
echo Checking runtime and ports...
where python >>"%LOG%" 2>&1
where py >>"%LOG%" 2>&1
where node >>"%LOG%" 2>&1
where npm >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo --- Managed Python environment ---
if exist "%PY%" ("%PY%" --version >>"%LOG%" 2>&1 & "%PY%" -c "import fastapi,uvicorn,pandas,openpyxl,multipart,pydantic,dotenv; print('Backend dependencies OK')" >>"%LOG%" 2>&1) else (echo Missing: %PY% >>"%LOG%")
>>"%LOG%" echo.
>>"%LOG%" echo --- Port 8000 listeners (PID included) ---
netstat -ano | findstr ":8000" >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo --- Process owning port 8000 ---
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue; if($c){$c | Select-Object LocalAddress,LocalPort,OwningProcess | Format-Table -AutoSize; $c.OwningProcess | Sort-Object -Unique | ForEach-Object {Get-CimInstance Win32_Process -Filter \"ProcessId=$($_)\" | Select-Object ProcessId,Name,ExecutablePath,CommandLine | Format-List}} else {Write-Output \"No listener on port 8000\"}" >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo --- Health endpoint ---
curl.exe -i --max-time 5 http://127.0.0.1:8000/health >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo --- API version endpoint ---
curl.exe -i --max-time 5 http://127.0.0.1:8000/api/version >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo --- Frontend endpoint ---
curl.exe -i --max-time 5 http://127.0.0.1:5173/ >>"%LOG%" 2>&1
>>"%LOG%" echo.
>>"%LOG%" echo --- Backend runtime log tail ---
if exist backend_runtime.log powershell -NoProfile -Command "Get-Content 'backend_runtime.log' -Tail 100" >>"%LOG%" 2>&1
echo Diagnostics saved to: %LOG%
type "%LOG%"
pause
