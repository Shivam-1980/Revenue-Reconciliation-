@echo off
setlocal
cd /d "%~dp0.."
if "%APP_ENV%"=="" set APP_ENV=hosted
if "%DATABASE_URL%"=="" (
  echo ERROR: DATABASE_URL is required. Configure it in your deployment secret manager.
  exit /b 2
)
python -m alembic upgrade head
if errorlevel 1 (
  echo ERROR: Database migration failed. Do not start hosted business routes.
  exit /b 1
)
python scripts\hosted_readiness.py
if errorlevel 1 exit /b 1
echo Hosted metadata migration and readiness checks passed.
