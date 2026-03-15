@echo off
title PolyBot - Live Logs

echo.
echo  ====================================
echo   PolyBot Live Logs
echo  ====================================
echo   Press Ctrl+C to stop viewing logs
echo  ====================================
echo.

docker compose logs -f engine dashboard

pause
