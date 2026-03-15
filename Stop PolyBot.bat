@echo off
title PolyBot - Stopping...

echo.
echo  ====================================
echo   Stopping PolyBot...
echo  ====================================
echo.

docker compose down

echo.
echo  PolyBot stopped.
echo  Database data is preserved.
echo.
echo  To restart: double-click "Start PolyBot.bat"
echo.

pause
