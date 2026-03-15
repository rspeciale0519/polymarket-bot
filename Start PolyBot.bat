@echo off
title PolyBot - Starting...

echo.
echo  ====================================
echo   PolyBot Market Maker
echo  ====================================
echo.

:: Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Docker Desktop is not running.
    echo  Please start Docker Desktop and try again.
    echo.
    pause
    exit /b 1
)

:: Create .env from example if it doesn't exist
if not exist ".env" (
    echo  [SETUP] Creating .env config file...
    copy ".env.example" ".env" >nul
    echo  [SETUP] Created .env - edit this file with your settings.
    echo.
)

echo  [1/4] Starting database...
docker compose up -d postgres
echo.

echo  [2/4] Running database migration...
docker compose up migrate --build
echo.

echo  [3/4] Seeding default settings...
docker compose up seed --build
echo.

echo  [4/4] Starting engine and dashboard...
docker compose up -d engine dashboard --build
echo.

echo  ====================================
echo   PolyBot is running!
echo  ====================================
echo.
echo   Dashboard:  http://localhost:3000
echo   Mode:       Paper Trading
echo.
echo   To configure: edit the .env file
echo   To stop:      double-click "Stop PolyBot.bat"
echo   To view logs: double-click "PolyBot Logs.bat"
echo.

:: Open the dashboard in the default browser
start http://localhost:3000

pause
