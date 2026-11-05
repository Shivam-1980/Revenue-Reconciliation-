@echo off
setlocal
set "CERT=%~dp0backend\data\certs\eko-local.crt"
if not exist "%CERT%" (
  echo The local certificate does not exist yet. Set EKO_HTTPS=true in backend\.env and run start.bat once, or run:
  echo   python backend\make_local_cert.py
  pause
  exit /b 1
)
echo Adding the Eko local HTTPS certificate to YOUR Windows user's trusted certificates.
echo Windows will ask you to confirm: choose Yes. Only this user on this PC trusts it.
certutil -user -addstore -f Root "%CERT%"
if errorlevel 1 (echo Could not add the certificate. & pause & exit /b 1)
echo Done. Restart the browser; https://127.0.0.1:5173 will open without a warning.
pause
