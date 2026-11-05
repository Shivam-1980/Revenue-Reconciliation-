@echo off
REM Walks the owner through: key copy, backups away from this disk, disk encryption (BitLocker).
cd /d "%~dp0backend"
set "PY="
for /d %%D in ("%LOCALAPPDATA%\EkoSBI\venv_*") do if exist "%%D\Scripts\python.exe" set "PY=%%D\Scripts\python.exe"
if defined PY (
  "%PY%" owner_security_steps.py
) else (
  python owner_security_steps.py
)
pause
