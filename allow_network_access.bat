@echo off
REM Opens TCP port 8000 for the private network so the other agent can reach this PC (run as administrator, once).
net session >nul 2>&1
if errorlevel 1 (
  echo Please right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)
netsh advfirewall firewall delete rule name="Eko Reconciliation API" >nul 2>&1
netsh advfirewall firewall add rule name="Eko Reconciliation API" dir=in action=allow protocol=TCP localport=8000 profile=private
echo.
echo Done: port 8000 is open on the PRIVATE network profile only. To remove it later:
echo   netsh advfirewall firewall delete rule name="Eko Reconciliation API"
pause
