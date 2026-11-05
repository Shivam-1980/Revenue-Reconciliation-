@echo off
setlocal EnableExtensions
cd /d "%~dp0frontend"
title EKO Revenue Reconciliation - Frontend Production Build
set "LOG=%~dp0frontend_build_verification.log"
>"%LOG%" echo EKO Revenue Reconciliation - Frontend Build Verification
>>"%LOG%" echo Started: %DATE% %TIME%

echo ============================================================
echo EKO Revenue Reconciliation - Frontend Production Build
echo Log: %LOG%
echo ============================================================
where node >>"%LOG%" 2>&1
if errorlevel 1 goto NO_NODE
where npm >>"%LOG%" 2>&1
if errorlevel 1 goto NO_NPM
node --version
echo Node:>>"%LOG%"
node --version >>"%LOG%" 2>&1
npm --version
echo npm:>>"%LOG%"
npm --version >>"%LOG%" 2>&1

echo [1/5] Checking npm registry connectivity...
call npm.cmd ping --registry=https://registry.npmjs.org/ >>"%LOG%" 2>&1
if errorlevel 1 (
  echo WARNING: npm registry ping failed. Trying install anyway using cache and retries.
  >>"%LOG%" echo Registry ping failed; install will still be attempted.
) else (
  echo Registry reachable.
)

echo [2/5] Installing exact declared dependencies...
call npm.cmd install --no-audit --no-fund --prefer-offline --fetch-retries=2 --fetch-retry-mintimeout=5000 --fetch-retry-maxtimeout=20000 --fetch-timeout=60000 >>"%LOG%" 2>&1
if errorlevel 1 goto INSTALL_FAILED

echo [3/5] Checking Vite availability...
call npm.cmd exec -- vite --version >>"%LOG%" 2>&1
if errorlevel 1 goto VITE_MISSING

echo [4/5] Running production build...
call npm.cmd run build >>"%LOG%" 2>&1
if errorlevel 1 goto BUILD_FAILED

echo [5/5] Validating build output...
if not exist "dist\index.html" goto OUTPUT_FAILED
if not exist "dist\assets" goto ASSETS_FAILED
>>"%LOG%" echo RESULT=PASS
>>"%LOG%" echo Finished: %DATE% %TIME%
echo.
echo SUCCESS: Production build passed. Check frontend\dist\ and the log file.
pause
exit /b 0

:NO_NODE
echo ERROR: Node.js is not installed or not on PATH.
>>"%LOG%" echo RESULT=FAIL_NODE_MISSING
goto FAIL
:NO_NPM
echo ERROR: npm is not installed or not on PATH.
>>"%LOG%" echo RESULT=FAIL_NPM_MISSING
goto FAIL
:INSTALL_FAILED
echo ERROR: npm dependency installation failed. Check internet, proxy/VPN, firewall and the log.
>>"%LOG%" echo RESULT=FAIL_NPM_INSTALL
 goto FAIL
:VITE_MISSING
echo ERROR: Vite is unavailable after dependency installation.
>>"%LOG%" echo RESULT=FAIL_VITE_MISSING
goto FAIL
:BUILD_FAILED
echo ERROR: Vite production build failed. Open the log and inspect the first compiler error.
>>"%LOG%" echo RESULT=FAIL_BUILD
 goto FAIL
:OUTPUT_FAILED
echo ERROR: Build command completed but dist\index.html is missing.
>>"%LOG%" echo RESULT=FAIL_NO_INDEX
 goto FAIL
:ASSETS_FAILED
echo ERROR: Build command completed but dist\assets is missing.
>>"%LOG%" echo RESULT=FAIL_NO_ASSETS
 goto FAIL
:FAIL
echo.
echo Full diagnostics saved to: %LOG%
>>"%LOG%" echo Finished: %DATE% %TIME%
pause
exit /b 1
